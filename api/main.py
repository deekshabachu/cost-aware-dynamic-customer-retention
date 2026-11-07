"""FastAPI endpoints for churn inference and retention decisions."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
import hmac
import logging
import os
import threading
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, sessionmaker

from database.config import create_database_engine
from database.base import utc_now
from database.initialize import initialize_database
from database.models import (
    CustomerActivity,
    Offer,
    Order,
    OrderItem,
    Product,
    RetentionBudgetSetting,
    RetentionIntervention,
    RetentionOfferClaim,
    RetentionOfferRedemption,
    RetentionOfferValidity,
    RetentionPrediction,
    User,
)
from retention import CustomerInput, decide_retention
from services.churn_inference import ChurnInferenceService
from services.customer_retention import (
    MODEL_FEATURES_EVENT_TYPE,
    ExistingActiveInterventionError,
    MissingCustomerFeaturesError,
    UnknownCustomerError,
    evaluate_all_customer_retention,
    evaluate_customer_retention,
    refresh_customer_retention,
)
from services.orders import (
    UnknownProductsError,
    UnavailableProductsError,
    calculate_order_quote,
    create_simulated_order,
    get_customer_orders,
    RetentionOfferUnavailableError,
)
from services.commerce_config import CommerceConfig

from .schemas import (
    AdminAccessTokenResponse,
    AdminAllocationDecisionResponse,
    AdminAllocationSummaryResponse,
    AdminBudgetResponse,
    AdminBudgetUpdateRequest,
    AdminBulkEvaluationRequest,
    AdminCustomerEvaluationRequest,
    AdminCustomerEvaluationResponse,
    AdminCurrentDecisionResponse,
    AdminDashboardResponse,
    AdminLoginRequest,
    AccessTokenResponse,
    AuthenticatedUserResponse,
    CheckoutRequest,
    CustomerRegistrationRequest,
    CustomerRetentionOfferResponse,
    AssignedRetentionInterventionResponse,
    CustomerOfferDetailsResponse,
    LoginRequest,
    OfferResponse,
    OrderItemResponse,
    OrderResponse,
    OrderPricingResponse,
    OrderQuoteRequest,
    OrderQuoteResponse,
    PredictionRequest,
    PredictionResponse,
    ProductResponse,
    RetentionCustomerDecisionResponse,
    RetentionDecisionRequest,
    RetentionDecisionResponse,
    RetentionRefreshRequest,
    RetentionRefreshResponse,
    RetentionOfferClaimResponse,
    RetentionSummaryResponse,
)
from .auth import (
    InvalidTokenError,
    TOKEN_LIFETIME_SECONDS,
    create_access_token,
    dummy_password_hash,
    hash_password,
    validate_auth_secret,
    verify_access_token,
    verify_password,
)


logger = logging.getLogger(__name__)


def create_app(
    *,
    database_engine: Engine | None = None,
    inference_service: ChurnInferenceService | None = None,
    inference_service_factory: Callable[[], ChurnInferenceService] | None = None,
    auth_secret_key: str | None = None,
    admin_email: str | None = None,
    admin_password_hash: str | None = None,
    commerce_config: CommerceConfig | None = None,
) -> FastAPI:
    """Create an app with injectable database and inference dependencies.

    Injection keeps API tests isolated from the configured live database and
    makes missing model artifacts reportable without preventing other routes
    from starting.
    """
    target_engine = database_engine or create_database_engine()
    session_factory = sessionmaker(bind=target_engine, expire_on_commit=False)
    service_factory = inference_service_factory or ChurnInferenceService
    target_commerce_config = commerce_config or CommerceConfig.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(
            target_engine,
            offer_validity_days=target_commerce_config.offer_validity_days,
        )
        app.state.inference_service = inference_service
        app.state.inference_unavailable = False
        if app.state.inference_service is None:
            try:
                # Loaded once per app process; requests reuse this instance.
                app.state.inference_service = service_factory()
            except (FileNotFoundError, RuntimeError, ValueError):
                logger.error(
                    "Churn inference artifacts could not be loaded; "
                    "the prediction endpoint will return 503."
                )
                app.state.inference_unavailable = True
        yield

    app = FastAPI(
        title="Customer Retention Prototype API",
        description=(
            "Churn probabilities estimate the dataset-defined churn flag. "
            "The dataset does not establish a validated future prediction horizon."
        ),
        lifespan=lifespan,
    )
    app.state.database_engine = target_engine
    app.state.session_factory = session_factory
    app.state.commerce_config = target_commerce_config
    # Prevent duplicate concurrent bulk allocations within this API process.
    app.state.bulk_evaluation_lock = threading.Lock()
    app.state.auth_secret_key = (
        auth_secret_key if auth_secret_key is not None else os.getenv("AUTH_SECRET_KEY")
    )
    app.state.admin_email = admin_email if admin_email is not None else os.getenv("ADMIN_EMAIL")
    app.state.admin_password_hash = (
        admin_password_hash
        if admin_password_hash is not None
        else os.getenv("ADMIN_PASSWORD_HASH")
    )

    frontend_origins = [
        origin.strip()
        for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]
    if "*" in frontend_origins:
        raise ValueError("FRONTEND_ORIGINS must list exact trusted origins, not '*'.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def get_session():
        with session_factory() as session:
            yield session

    SessionDependency = Annotated[Session, Depends(get_session)]
    bearer_scheme = HTTPBearer(auto_error=False)

    def signing_secret(request: Request) -> str:
        secret = request.app.state.auth_secret_key
        try:
            # Validate strength before using the configured key.
            validate_auth_secret(secret)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured. Set a strong AUTH_SECRET_KEY.",
            ) from exc
        return secret

    def get_current_customer(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
        ],
        session: SessionDependency,
    ) -> User:
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise unauthorized
        try:
            user_id = verify_access_token(
                credentials.credentials, signing_secret(request)
            )
        except (InvalidTokenError, ValueError) as exc:
            raise unauthorized from exc
        user = session.get(User, user_id)
        if user is None or user.role != "customer":
            raise unauthorized
        return user

    CurrentCustomer = Annotated[User, Depends(get_current_customer)]

    def get_current_admin(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
        ],
    ) -> None:
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid administrator bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise unauthorized
        try:
            # Subject zero is reserved for tokens issued by admin credential
            # verification. Persisted customer accounts always have positive IDs.
            subject = verify_access_token(
                credentials.credentials, signing_secret(request)
            )
        except (InvalidTokenError, ValueError) as exc:
            raise unauthorized from exc
        if subject != 0:
            raise unauthorized

    CurrentAdmin = Annotated[None, Depends(get_current_admin)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post(
        "/auth/register",
        response_model=AuthenticatedUserResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def register_customer(
        request: CustomerRegistrationRequest,
        session: SessionDependency,
    ) -> AuthenticatedUserResponse:
        existing = session.scalar(
            select(User).where(func.lower(User.email) == request.email)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        user = User(
            name=request.name,
            email=request.email,
            password_hash=hash_password(request.password.get_secret_value()),
            role="customer",
        )
        session.add(user)
        try:
            session.commit()
            session.refresh(user)
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            ) from exc
        return AuthenticatedUserResponse(id=user.id, email=user.email)

    @app.post("/auth/login", response_model=AccessTokenResponse)
    def login_customer(
        request: LoginRequest,
        session: SessionDependency,
        http_request: Request,
    ) -> AccessTokenResponse:
        secret = signing_secret(http_request)
        user = session.scalar(
            select(User).where(func.lower(User.email) == request.email)
        )
        password = request.password.get_secret_value()
        stored_hash = (
            user.password_hash
            if user is not None and user.role == "customer"
            else dummy_password_hash()
        )
        password_matches = verify_password(password, stored_hash)
        if not password_matches or user is None or user.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email or password is incorrect.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(user.id, secret)
        return AccessTokenResponse(
            access_token=token,
            expires_in=TOKEN_LIFETIME_SECONDS,
            user=AuthenticatedUserResponse(id=user.id, email=user.email),
        )

    @app.get("/auth/me", response_model=AuthenticatedUserResponse)
    def current_customer(user: CurrentCustomer) -> AuthenticatedUserResponse:
        return AuthenticatedUserResponse(id=user.id, email=user.email)

    @app.post("/admin/auth/login", response_model=AdminAccessTokenResponse)
    def admin_login(
        request: AdminLoginRequest,
        http_request: Request,
    ) -> AdminAccessTokenResponse:
        configured_email = http_request.app.state.admin_email
        password_hash = http_request.app.state.admin_password_hash
        if (
            not isinstance(configured_email, str)
            or not configured_email.strip()
            or not isinstance(password_hash, str)
            or not password_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Administrator authentication is not configured.",
            )
        email_matches = hmac.compare_digest(
            request.email, configured_email.strip().lower()
        )
        password_matches = verify_password(
            request.password.get_secret_value(), password_hash
        )
        if not email_matches or not password_matches:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Administrator email or password is incorrect.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = create_access_token(0, signing_secret(http_request))
        return AdminAccessTokenResponse(
            access_token=token,
            expires_in=TOKEN_LIFETIME_SECONDS,
        )

    def build_admin_dashboard(session: Session) -> AdminDashboardResponse:
        customer_ids = session.scalars(
            select(User.id).where(User.role == "customer").order_by(User.id)
        ).all()
        snapshot_customer_ids = set(
            session.scalars(
                select(CustomerActivity.user_id)
                .distinct()
                .where(CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE)
            ).all()
        )
        latest_prediction_id = (
            select(RetentionPrediction.id)
            .where(RetentionPrediction.user_id == User.id)
            .order_by(RetentionPrediction.predicted_at.desc(), RetentionPrediction.id.desc())
            .limit(1)
            .correlate(User)
            .scalar_subquery()
        )
        latest_intervention_id = (
            select(RetentionIntervention.id)
            .where(RetentionIntervention.user_id == User.id)
            .order_by(RetentionIntervention.created_at.desc(), RetentionIntervention.id.desc())
            .limit(1)
            .correlate(User)
            .scalar_subquery()
        )
        # Start with customer accounts and LEFT JOIN each account's latest
        # records, keeping customers who have not been evaluated or assigned.
        current_rows = session.execute(
            select(User, RetentionPrediction, RetentionIntervention)
            .outerjoin(
                RetentionPrediction,
                RetentionPrediction.id == latest_prediction_id,
            )
            .outerjoin(
                RetentionIntervention,
                RetentionIntervention.id == latest_intervention_id,
            )
            .options(
                joinedload(RetentionIntervention.offer),
                joinedload(RetentionIntervention.claim),
                joinedload(RetentionIntervention.redemption),
            )
            .where(User.role == "customer")
            .order_by(User.id)
        ).unique().all()
        decisions: list[AdminCurrentDecisionResponse] = []
        intervention_counts: dict[str, int] = {}
        customers_with_offers = 0
        customers_with_no_offer = 0
        customers_with_predictions = 0
        for user, prediction, intervention in current_rows:
            code = intervention.offer.code if intervention is not None else None
            claim_status = None
            if intervention is not None:
                claim_status = (
                    "redeemed"
                    if intervention.redemption is not None
                    else "no_offer"
                    if code == "NO_OFFER"
                    or intervention.status != "active"
                    or not intervention.offer.active
                    else "claimed"
                    if intervention.claim is not None
                    else "assigned"
                )
                intervention_counts[code] = intervention_counts.get(code, 0) + 1
                if code == "NO_OFFER":
                    customers_with_no_offer += 1
                elif intervention.status == "active":
                    customers_with_offers += 1
            if prediction is not None:
                customers_with_predictions += 1
            historical_revenue = (
                float(prediction.customer_value) if prediction is not None else None
            )
            decisions.append(
                AdminCurrentDecisionResponse(
                    customer_id=user.id,
                    customer_email=user.email,
                    has_feature_snapshot=user.id in snapshot_customer_ids,
                    churn_probability=(
                        float(prediction.churn_probability)
                        if prediction is not None
                        else None
                    ),
                    historical_revenue=historical_revenue,
                    priority_score=(
                        float(intervention.priority_score)
                        if intervention is not None
                        else (
                            float(prediction.churn_probability) * historical_revenue
                            if prediction is not None and historical_revenue is not None
                            else None
                        )
                    ),
                    intervention_code=code,
                    estimated_intervention_cost=(
                        float(intervention.intervention_cost)
                        if intervention is not None
                        else None
                    ),
                    status=intervention.status if intervention is not None else None,
                    claim_status=claim_status,
                    claimed_at=(
                        intervention.claim.claimed_at
                        if intervention is not None and intervention.claim is not None
                        else None
                    ),
                    redeemed_order_id=(
                        intervention.redemption.order_id
                        if intervention is not None and intervention.redemption is not None
                        else None
                    ),
                    redemption_discount_amount=(
                        float(intervention.redemption.discount_amount)
                        if intervention is not None and intervention.redemption is not None
                        else None
                    ),
                    redemption_shipping_discount=(
                        float(intervention.redemption.shipping_discount)
                        if intervention is not None and intervention.redemption is not None
                        else None
                    ),
                    free_shipping_applied=(
                        intervention.redemption.free_shipping_applied
                        if intervention is not None and intervention.redemption is not None
                        else False
                    ),
                    redeemed_at=(
                        intervention.redemption.redeemed_at
                        if intervention is not None and intervention.redemption is not None
                        else None
                    ),
                )
            )

        setting = session.get(RetentionBudgetSetting, 1)
        latest_allocation = (
            AdminAllocationSummaryResponse.model_validate(setting.last_allocation)
            if setting is not None and setting.last_allocation is not None
            else None
        )
        return AdminDashboardResponse(
            total_customers=len(customer_ids),
            customers_with_predictions=customers_with_predictions,
            customers_with_offers=customers_with_offers,
            customers_with_no_offer=customers_with_no_offer,
            intervention_counts=intervention_counts,
            customers_without_feature_snapshot=sorted(
                set(customer_ids) - snapshot_customer_ids
            ),
            budget_configured=setting is not None,
            current_budget=float(setting.total_budget) if setting is not None else None,
            latest_allocation=latest_allocation,
            current_decisions=decisions,
        )

    @app.get("/admin/dashboard", response_model=AdminDashboardResponse)
    def admin_dashboard(
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> AdminDashboardResponse:
        return build_admin_dashboard(session)

    @app.put("/admin/budget", response_model=AdminBudgetResponse)
    def save_retention_budget(
        request: AdminBudgetUpdateRequest,
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> AdminBudgetResponse:
        try:
            setting = session.get(RetentionBudgetSetting, 1)
            if setting is None:
                setting = RetentionBudgetSetting(
                    id=1, total_budget=Decimal(str(request.total_budget))
                )
                session.add(setting)
            else:
                setting.total_budget = Decimal(str(request.total_budget))
                setting.updated_at = utc_now()
            session.commit()
            return AdminBudgetResponse(
                budget_configured=True,
                current_budget=float(setting.total_budget),
            )
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not save the retention budget.")
            raise HTTPException(
                status_code=500, detail="Could not save the retention budget."
            ) from exc

    @app.post("/admin/retention/allocate", response_model=AdminDashboardResponse)
    def run_admin_retention_allocation(
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> AdminDashboardResponse:
        setting = session.get(RetentionBudgetSetting, 1)
        if setting is None:
            raise HTTPException(
                status_code=409,
                detail="Save a retention budget before running an allocation.",
            )
        service = app.state.inference_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Churn inference is unavailable because model artifacts could not be loaded.",
            )

        all_customer_ids = session.scalars(
            select(User.id).where(User.role == "customer").order_by(User.id)
        ).all()
        snapshot_customer_ids = set(
            session.scalars(
                select(CustomerActivity.user_id)
                .distinct()
                .where(CustomerActivity.event_type == MODEL_FEATURES_EVENT_TYPE)
            ).all()
        )
        selected_ids = [
            customer_id
            for customer_id in all_customer_ids
            if customer_id in snapshot_customer_ids
        ]
        if not selected_ids:
            raise HTTPException(
                status_code=409,
                detail="No customers have stored model feature snapshots to allocate.",
            )

        try:
            result = refresh_customer_retention(
                session=session,
                inference_service=service,
                customer_ids=selected_ids,
                total_budget=float(setting.total_budget),
                commit=False,
                offer_validity_days=app.state.commerce_config.offer_validity_days,
            )
            created_at = utc_now()
            latest_allocation = AdminAllocationSummaryResponse(
                initial_budget=result.decisions.summary.initial_budget,
                total_estimated_budget_allocated=(
                    result.decisions.summary.total_estimated_budget_allocated
                ),
                remaining_budget=result.decisions.summary.remaining_budget,
                intervention_counts=result.decisions.summary.intervention_counts,
                customer_count=len(selected_ids),
                skipped_customer_ids=sorted(
                    set(all_customer_ids) - set(selected_ids)
                ),
                created_at=created_at,
                decisions=[
                    AdminAllocationDecisionResponse(
                        customer_id=decision.customer_id,
                        churn_probability=decision.churn_probability,
                        historical_revenue=decision.historical_revenue,
                        priority_score=decision.priority_score,
                        intervention_code=decision.selected_intervention,
                        estimated_intervention_cost=decision.estimated_intervention_cost,
                    )
                    for decision in result.decisions.customers
                ],
            )
            setting.last_allocation = latest_allocation.model_dump(mode="json")
            setting.updated_at = created_at
            # Persist predictions, interventions, and the allocation summary in
            # one transaction so the dashboard cannot report a partial run.
            session.commit()
        except (MissingCustomerFeaturesError, ValueError) as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not persist the admin retention allocation.")
            raise HTTPException(
                status_code=500, detail="Could not persist the retention allocation."
            ) from exc
        except Exception as exc:
            session.rollback()
            logger.exception("Admin retention allocation failed.")
            raise HTTPException(
                status_code=500, detail="Retention allocation failed."
            ) from exc

        return build_admin_dashboard(session)

    @app.post(
        "/admin/retention/evaluate-all",
        response_model=AdminDashboardResponse,
    )
    def evaluate_all_admin_customers(
        request: AdminBulkEvaluationRequest,
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> AdminDashboardResponse:
        """Evaluate all snapshot-backed customers in one protected transaction."""
        lock = app.state.bulk_evaluation_lock
        if not lock.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A bulk retention evaluation is already in progress.",
            )
        try:
            # SQLite uses a write reservation before reading the shared budget,
            # preventing two concurrent calls from allocating the same balance.
            if session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")

            setting = session.get(RetentionBudgetSetting, 1)
            if setting is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Save a retention budget before running bulk evaluation.",
                )
            inference = app.state.inference_service
            if inference is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        "Churn inference is unavailable because model artifacts "
                        "could not be loaded."
                    ),
                )

            result = evaluate_all_customer_retention(
                session=session,
                inference_service=inference,
                total_budget=float(setting.total_budget),
                eligibility_threshold=request.eligibility_threshold,
                commit=False,
                offer_validity_days=app.state.commerce_config.offer_validity_days,
            )
            summary = AdminAllocationSummaryResponse(
                initial_budget=result.initial_budget,
                total_estimated_budget_allocated=result.total_committed_reserved_cost,
                remaining_budget=result.remaining_budget,
                intervention_counts=result.intervention_counts,
                customer_count=result.customers_evaluated,
                skipped_customer_ids=[
                    row.customer_id
                    for row in result.customer_outcomes
                    if not row.has_feature_snapshot
                ],
                created_at=result.created_at,
                eligibility_threshold=result.threshold,
                total_accounts=result.total_accounts,
                customers_evaluated=result.customers_evaluated,
                customers_missing_feature_snapshot=(
                    result.customers_missing_feature_snapshot
                ),
                customers_below_threshold=result.customers_below_threshold,
                customers_eligible=result.customers_eligible,
                customers_receiving_no_offer=result.customers_receiving_no_offer,
                existing_offers_preserved=result.existing_offers_preserved,
                existing_redeemed_offers_preserved=(
                    result.existing_redeemed_offers_preserved
                ),
                new_offers_generated=result.new_offers_generated,
                total_new_offer_cost=result.total_new_offer_cost,
                total_committed_reserved_cost=result.total_committed_reserved_cost,
                decisions=[
                    AdminAllocationDecisionResponse(
                        customer_id=row.customer_id,
                        customer_email=row.customer_email,
                        has_feature_snapshot=row.has_feature_snapshot,
                        churn_probability=row.churn_probability,
                        historical_revenue=row.historical_revenue,
                        priority_score=row.priority_score,
                        eligible=row.eligible,
                        intervention_code=row.intervention_code,
                        estimated_intervention_cost=row.estimated_intervention_cost,
                        status=row.status,
                        preserved_existing_offer=row.preserved_existing_offer,
                        preserved_redeemed_offer=row.preserved_redeemed_offer,
                        new_offer_generated=row.new_offer_generated,
                    )
                    for row in result.customer_outcomes
                ],
            )
            setting.last_allocation = summary.model_dump(mode="json")
            setting.updated_at = result.created_at
            # The budget setting, predictions, interventions, and run summary
            # share one commit; failures roll the whole operation back.
            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not persist the bulk retention evaluation.")
            raise HTTPException(
                status_code=500,
                detail="Could not persist the bulk retention evaluation.",
            ) from exc
        except Exception as exc:
            session.rollback()
            logger.exception("Bulk retention evaluation failed.")
            raise HTTPException(
                status_code=500, detail="Bulk retention evaluation failed."
            ) from exc
        finally:
            lock.release()

        return build_admin_dashboard(session)

    @app.post(
        "/admin/customers/{customer_id}/evaluate",
        response_model=AdminCustomerEvaluationResponse,
    )
    def evaluate_admin_customer(
        customer_id: int,
        request: AdminCustomerEvaluationRequest,
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> AdminCustomerEvaluationResponse:
        setting = session.get(RetentionBudgetSetting, 1)
        if setting is None:
            raise HTTPException(
                status_code=409,
                detail="Save a retention budget before evaluating a customer.",
            )
        service = app.state.inference_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Churn inference is unavailable because model artifacts could not be loaded.",
            )
        try:
            result = evaluate_customer_retention(
                session=session,
                inference_service=service,
                customer_id=customer_id,
                total_budget=float(setting.total_budget),
                eligibility_threshold=request.eligibility_threshold,
                commit=False,
                offer_validity_days=app.state.commerce_config.offer_validity_days,
            )
            session.commit()
        except UnknownCustomerError as exc:
            session.rollback()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MissingCustomerFeaturesError as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ExistingActiveInterventionError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not persist the selected-customer evaluation.")
            raise HTTPException(
                status_code=500,
                detail="Could not persist the selected-customer evaluation.",
            ) from exc
        except Exception as exc:
            session.rollback()
            logger.exception("Selected-customer evaluation failed.")
            raise HTTPException(
                status_code=500, detail="Selected-customer evaluation failed."
            ) from exc

        decision = result.decision.customers[0]
        return AdminCustomerEvaluationResponse(
            customer_id=customer_id,
            customer_email=result.customer_email,
            churn_probability=result.prediction.churn_probability,
            model_version=result.prediction.model_version,
            eligibility_threshold=request.eligibility_threshold,
            eligible=decision.eligible,
            intervention_code=decision.selected_intervention,
            estimated_intervention_cost=decision.estimated_intervention_cost,
            budget_available=result.budget_available,
            budget_remaining=decision.budget_remaining,
            budget_allowed_assignment=(
                decision.eligible and decision.selected_intervention != "NO_OFFER"
            ),
            decision_explanation=decision.decision_explanation,
        )

    @app.get("/offers", response_model=list[OfferResponse])
    def list_offers(_: CurrentAdmin, session: SessionDependency) -> list[OfferResponse]:
        try:
            offers = session.scalars(
                select(Offer).where(Offer.active.is_(True)).order_by(Offer.code)
            ).all()
        except SQLAlchemyError as exc:
            logger.exception("Offer listing failed.")
            raise HTTPException(status_code=500, detail="Could not load offers.") from exc

        return [
            OfferResponse(
                code=offer.code,
                name=offer.name,
                description=offer.description,
                discount_percentage=(
                    float(offer.discount_percentage)
                    if offer.discount_percentage is not None
                    else None
                ),
                maximum_cost=float(offer.maximum_cost),
            )
            for offer in offers
        ]

    def order_pricing_response(
        subtotal_amount: Decimal,
        shipping_fee: Decimal,
        tax_rate: Decimal,
        tax_amount: Decimal,
        total_amount: Decimal,
        discount_amount: Decimal = Decimal("0.00"),
        applied_offer_name: str | None = None,
        applied_offer_description: str | None = None,
        shipping_discount_amount: Decimal = Decimal("0.00"),
    ) -> OrderPricingResponse:
        return OrderPricingResponse(
            subtotal_amount=f"{subtotal_amount:.2f}",
            discount_amount=f"{discount_amount:.2f}",
            applied_offer_name=applied_offer_name,
            applied_offer_description=applied_offer_description,
            shipping_fee=f"{shipping_fee:.2f}",
            shipping_discount_amount=f"{shipping_discount_amount:.2f}",
            tax_rate_percent=float(tax_rate * 100),
            tax_amount=f"{tax_amount:.2f}",
            total_amount=f"{total_amount:.2f}",
        )

    def order_response(order: Order) -> OrderResponse:
        return OrderResponse(
            id=order.id,
            status=order.status,
            created_at=order.created_at,
            total_amount=f"{Decimal(order.total_amount):.2f}",
            pricing=(
                order_pricing_response(
                    subtotal_amount=Decimal(order.pricing.subtotal_amount),
                    shipping_fee=Decimal(order.pricing.shipping_fee),
                    tax_rate=Decimal(order.pricing.tax_rate),
                    tax_amount=Decimal(order.pricing.tax_amount),
                    total_amount=Decimal(order.total_amount),
                    discount_amount=(
                        Decimal(order.retention_redemption.discount_amount)
                        if order.retention_redemption is not None
                        else Decimal("0.00")
                    ),
                    applied_offer_name=(
                        order.retention_redemption.offer.name
                        if order.retention_redemption is not None
                        else None
                    ),
                    applied_offer_description=(
                        order.retention_redemption.offer.description
                        if order.retention_redemption is not None
                        else None
                    ),
                    shipping_discount_amount=(
                        Decimal(order.retention_redemption.shipping_discount)
                        if order.retention_redemption is not None
                        else Decimal("0.00")
                    ),
                )
                if order.pricing is not None
                else None
            ),
            items=[
                OrderItemResponse(
                    product_id=item.product_id,
                    product_name=item.product.name,
                    category=item.product.category,
                    quantity=item.quantity,
                    unit_price=f"{Decimal(item.unit_price):.2f}",
                    line_total=f"{Decimal(item.unit_price) * item.quantity:.2f}",
                )
                for item in order.items
            ],
        )

    @app.get("/products", response_model=list[ProductResponse])
    def list_products(session: SessionDependency) -> list[ProductResponse]:
        """List the database catalogue so the checkout can use database IDs."""
        products = session.scalars(select(Product).order_by(Product.id)).all()
        return [
            ProductResponse(
                id=product.id,
                name=product.name,
                category=product.category,
                price=f"{Decimal(product.price):.2f}",
                stock=product.stock,
            )
            for product in products
        ]

    @app.post(
        "/orders/quote",
        response_model=OrderQuoteResponse,
    )
    def order_quote(
        request: OrderQuoteRequest,
        user: CurrentCustomer,
        session: SessionDependency,
    ) -> OrderQuoteResponse:
        try:
            quote = calculate_order_quote(
                session,
                [(item.product_id, item.quantity) for item in request.items],
                app.state.commerce_config,
                customer_id=user.id,
                apply_retention_offer=request.apply_retention_offer,
            )
        except RetentionOfferUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnknownProductsError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnavailableProductsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return OrderQuoteResponse(
            subtotal_amount=f"{quote.subtotal_amount:.2f}",
            shipping_fee=f"{quote.shipping_fee:.2f}",
            tax_rate_percent=float(quote.tax_rate * 100),
            discount_amount=f"{quote.discount_amount:.2f}",
            applied_offer_name=quote.applied_offer_name,
            applied_offer_description=quote.applied_offer_description,
            shipping_discount_amount=f"{quote.shipping_discount_amount:.2f}",
            tax_amount=f"{quote.tax_amount:.2f}",
            total_amount=f"{quote.total_amount:.2f}",
        )

    @app.post(
        "/orders/checkout",
        response_model=OrderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def checkout(
        request: CheckoutRequest,
        user: CurrentCustomer,
        session: SessionDependency,
    ) -> OrderResponse:
        try:
            order = create_simulated_order(
                session,
                user.id,
                [(item.product_id, item.quantity) for item in request.items],
                pricing_config=app.state.commerce_config,
                apply_retention_offer=request.apply_retention_offer,
            )
        except RetentionOfferUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnknownProductsError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnavailableProductsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            logger.exception("Could not save the simulated order.")
            raise HTTPException(
                status_code=500, detail="Could not save the order. Please try again."
            ) from exc
        return order_response(order)

    @app.get("/orders", response_model=list[OrderResponse])
    def order_history(
        user: CurrentCustomer,
        session: SessionDependency,
    ) -> list[OrderResponse]:
        try:
            return [
                order_response(order)
                for order in get_customer_orders(session, user.id)
            ]
        except SQLAlchemyError as exc:
            logger.exception("Could not load customer order history.")
            raise HTTPException(
                status_code=500, detail="Could not load order history."
            ) from exc

    @app.post("/predict", response_model=PredictionResponse)
    def predict(request: PredictionRequest) -> PredictionResponse:
        service = app.state.inference_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Churn inference is unavailable because model artifacts could not be loaded.",
            )
        try:
            prediction = service.predict_one(request.customer_id, request.features)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Churn inference request failed.")
            raise HTTPException(status_code=500, detail="Churn inference failed.") from exc

        return PredictionResponse(
            customer_id=prediction.customer_id,
            churn_probability=prediction.churn_probability,
            model_version=prediction.model_version,
        )

    @app.post("/retention/decide", response_model=RetentionDecisionResponse)
    def retention_decide(
        request: RetentionDecisionRequest,
        _: CurrentAdmin,
    ) -> RetentionDecisionResponse:
        customers = [
            CustomerInput(
                customer_id=customer.customer_id,
                churn_probability=customer.churn_probability,
                historical_revenue=customer.historical_revenue,
            )
            for customer in request.customers
        ]
        try:
            result = decide_retention(customers, total_budget=request.total_budget)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return RetentionDecisionResponse(
            customers=[
                RetentionCustomerDecisionResponse(
                    customer_id=item.customer_id,
                    churn_probability=item.churn_probability,
                    historical_revenue=item.historical_revenue,
                    priority_score=item.priority_score,
                    eligible=item.eligible,
                    selected_intervention=item.selected_intervention,
                    estimated_intervention_cost=item.estimated_intervention_cost,
                    decision_explanation=item.decision_explanation,
                    budget_remaining=item.budget_remaining,
                )
                for item in result.customers
            ],
            summary=RetentionSummaryResponse(
                initial_budget=result.summary.initial_budget,
                total_estimated_budget_allocated=(
                    result.summary.total_estimated_budget_allocated
                ),
                remaining_budget=result.summary.remaining_budget,
                intervention_counts=result.summary.intervention_counts,
            ),
        )

    @app.get(
        "/retention/offer", response_model=CustomerRetentionOfferResponse
    )
    def customer_retention_offer(
        user: CurrentCustomer,
        session: SessionDependency,
    ) -> CustomerRetentionOfferResponse:
        """Return only the signed-in customer's current paid offer, if any."""
        try:
            intervention = session.scalar(
                select(RetentionIntervention)
                .options(
                    joinedload(RetentionIntervention.offer),
                    joinedload(RetentionIntervention.claim),
                    joinedload(RetentionIntervention.validity),
                    joinedload(RetentionIntervention.redemption),
                )
                .where(
                    RetentionIntervention.user_id == user.id,
                    RetentionIntervention.status == "active",
                    RetentionIntervention.offer.has(Offer.active.is_(True)),
                )
                .order_by(
                    RetentionIntervention.created_at.desc(),
                    RetentionIntervention.id.desc(),
                )
                .limit(1)
            )
        except SQLAlchemyError as exc:
            logger.exception("Could not load the customer's assigned offer.")
            raise HTTPException(
                status_code=500,
                detail="The assigned offer could not be loaded.",
            ) from exc

        if intervention is None:
            return CustomerRetentionOfferResponse(assigned=False, intervention=None)

        offer = intervention.offer
        expires_at = (
            intervention.validity.expires_at
            if intervention.validity is not None
            else intervention.created_at
            + timedelta(days=app.state.commerce_config.offer_validity_days)
        )
        return CustomerRetentionOfferResponse(
            assigned=True,
            intervention=AssignedRetentionInterventionResponse(
                created_at=intervention.created_at,
                expires_at=expires_at,
                expired=expires_at <= utc_now(),
                offer=CustomerOfferDetailsResponse(
                    name=(
                        "Free shipping"
                        if offer.code == "FREE_SHIPPING"
                        else "Your LittleLeaf discount"
                    ),
                    description=offer.description,
                    discount_percentage=(
                        float(offer.discount_percentage)
                        if offer.discount_percentage is not None
                        else None
                    ),
                ),
                claimed=intervention.claim is not None,
                claimed_at=(
                    intervention.claim.claimed_at
                    if intervention.claim is not None
                    else None
                ),
                redeemed=intervention.redemption is not None,
            ),
        )

    @app.post(
        "/retention/offer/claim",
        response_model=RetentionOfferClaimResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def claim_customer_retention_offer(
        user: CurrentCustomer,
        session: SessionDependency,
    ) -> RetentionOfferClaimResponse:
        """Persist one simulated claim for the signed-in customer's current offer."""
        try:
            intervention = session.scalar(
                select(RetentionIntervention)
                .options(
                    joinedload(RetentionIntervention.offer),
                    joinedload(RetentionIntervention.validity),
                )
                .where(RetentionIntervention.user_id == user.id)
                .order_by(
                    RetentionIntervention.created_at.desc(),
                    RetentionIntervention.id.desc(),
                )
                .limit(1)
            )
            if intervention is None or intervention.offer.code == "NO_OFFER":
                raise HTTPException(
                    status_code=409,
                    detail="No active assigned offer is available to claim.",
                )
            existing_claim = session.scalar(
                select(RetentionOfferClaim).where(
                    RetentionOfferClaim.intervention_id == intervention.id
                )
            )
            if existing_claim is not None:
                raise HTTPException(
                    status_code=409,
                    detail="This assigned offer has already been claimed.",
                )
            if intervention.status != "active" or not intervention.offer.active:
                raise HTTPException(
                    status_code=409,
                    detail="This offer is no longer active and cannot be claimed.",
                )

            expires_at = (
                intervention.validity.expires_at
                if intervention.validity is not None
                else intervention.created_at
                + timedelta(days=app.state.commerce_config.offer_validity_days)
            )
            if expires_at <= utc_now():
                raise HTTPException(
                    status_code=409,
                    detail="Your offer has expired.",
                )

            if intervention.validity is None:
                session.add(
                    RetentionOfferValidity(
                        intervention_id=intervention.id,
                        expires_at=expires_at,
                    )
                )
            claim = RetentionOfferClaim(
                intervention_id=intervention.id,
                user_id=user.id,
            )
            session.add(claim)
            session.commit()
            session.refresh(claim)
            return RetentionOfferClaimResponse(
                claimed=True,
                claimed_at=claim.claimed_at,
                message="Offer claimed for this demo.",
            )
        except HTTPException:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="This offer is no longer available to claim.",
            ) from exc
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("Could not record the simulated offer claim.")
            raise HTTPException(
                status_code=500,
                detail="The offer claim could not be recorded.",
            ) from exc

    @app.post("/retention/refresh", response_model=RetentionRefreshResponse)
    def retention_refresh(
        request: RetentionRefreshRequest,
        _: CurrentAdmin,
        session: SessionDependency,
    ) -> RetentionRefreshResponse:
        # Persisted refreshes can change assigned offers and consume the shared
        # retention budget, so this is an administrator-only operation.
        service = app.state.inference_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Churn inference is unavailable because model artifacts could not be loaded.",
            )
        try:
            result = refresh_customer_retention(
                session=session,
                inference_service=service,
                customer_ids=request.customer_ids,
                total_budget=request.total_budget,
                offer_validity_days=app.state.commerce_config.offer_validity_days,
            )
        except UnknownCustomerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (MissingCustomerFeaturesError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            logger.exception("Could not persist the customer retention refresh.")
            raise HTTPException(
                status_code=500,
                detail="Could not persist the customer retention refresh.",
            ) from exc
        except Exception as exc:
            logger.exception("Customer retention refresh failed.")
            raise HTTPException(
                status_code=500, detail="Customer retention refresh failed."
            ) from exc

        return RetentionRefreshResponse(
            predictions=[
                PredictionResponse(
                    customer_id=prediction.customer_id,
                    churn_probability=prediction.churn_probability,
                    model_version=prediction.model_version,
                )
                for prediction in result.predictions
            ],
            decisions=[
                RetentionCustomerDecisionResponse(
                    customer_id=decision.customer_id,
                    churn_probability=decision.churn_probability,
                    historical_revenue=decision.historical_revenue,
                    priority_score=decision.priority_score,
                    eligible=decision.eligible,
                    selected_intervention=decision.selected_intervention,
                    estimated_intervention_cost=decision.estimated_intervention_cost,
                    decision_explanation=decision.decision_explanation,
                    budget_remaining=decision.budget_remaining,
                )
                for decision in result.decisions.customers
            ],
            summary=RetentionSummaryResponse(
                initial_budget=result.decisions.summary.initial_budget,
                total_estimated_budget_allocated=(
                    result.decisions.summary.total_estimated_budget_allocated
                ),
                remaining_budget=result.decisions.summary.remaining_budget,
                intervention_counts=result.decisions.summary.intervention_counts,
            ),
        )

    return app


app = create_app()

