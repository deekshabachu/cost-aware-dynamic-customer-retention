# Churn target and feature timing review

## Purpose

This note records what is currently known about the E-Commerce Customer Churn workbook used by this project, and what still needs confirmation before the model can be interpreted as a prospective churn predictor.

## Dataset facts verified locally

- Workbook: `data/raw/ecommerce_customer_churn.xlsx`, sheet `E Comm`.
- 5,630 customer rows and 20 columns: `CustomerID`, `Churn`, and 18 customer attributes.
- `Churn` is binary: 0 for the non-churn class and 1 for the churn class. The local data has 4,682 zero labels and 948 one labels (16.84% positive).
- `CustomerID` is unique and is excluded from model inputs.
- There are no duplicate complete rows or duplicate customer IDs in the workbook.
- Missing values occur in `Tenure`, `WarehouseToHome`, `HourSpendOnApp`, `OrderAmountHikeFromlastYear`, `CouponUsed`, `OrderCount`, and `DaySinceLastOrder`.

## What the source does not establish

The available dataset description presents `Churn` as a customer churn label, but does not give enough information to establish:

1. The operational rule used to assign churn (for example, a specific period without a purchase).
2. The date at which each customer's features were observed.
3. The feature lookback window or the future horizon covered by the label.
4. Whether all feature values were captured strictly before the label was assigned.

Therefore, this project currently treats `Churn` as the dataset's supplied binary label. It must not be described as a specifically defined future outcome, such as "will churn in the next 30/90 days," until that definition and timing are confirmed from authoritative dataset documentation.

The project materials identify the dataset as Dataset 1 in Liu et al. (2024), but the complete citation has not been supplied in the repository and could not be matched confidently to this exact 5,630-row workbook. The repository's historical notes also contain two conflicting Kaggle references: [a listing attributed to `ankitverma2010`](https://www.kaggle.com/datasets/ankitverma2010/ecommerce-customer-churn-analysis-and-prediction) and [a listing attributed to `wonderdavid`](https://www.kaggle.com/code/wonderdavid/e-commerce-customer-churn-prediction/data). Workbook core properties were checked for these candidate identifiers and for the dataset title or Liu citation; none established a match. The original source remains unverified. The project team must confirm the exact workbook source and complete Liu et al. reference before assigning a definitive attribution or citing the workbook as Dataset 1. Neither historical Kaggle reference establishes a churn horizon for this project copy.

## Feature timing and leakage review

No direct target column is included in the model inputs. The preprocessing code drops `Churn` and `CustomerID`; it fits imputers and one-hot encoders on training rows only. These are appropriate safeguards against direct target inclusion and preprocessing leakage.

The following behavioral fields need timing confirmation before they can be considered safe for prospective inference:

| Feature(s) | Why timing matters |
| --- | --- |
| `Tenure` | Strongest feature by the current model's importance. Its value may reflect elapsed relationship duration at an unclear snapshot date and could be closely tied to how churn was determined. |
| `Complain`, `SatisfactionScore` | Could be valid prior signals, but must have been recorded before the churn outcome/label cutoff. |
| `DaySinceLastOrder`, `OrderCount`, `CouponUsed` | Summarize purchasing behavior. Their aggregation period and cutoff must precede the churn label horizon. |
| `CashbackAmount`, `OrderAmountHikeFromlastYear` | Their reference periods are unspecified; confirm these summaries are not calculated using post-outcome activity. |
| Remaining demographic, preference, and account fields | Lower apparent direct leakage risk, but their snapshot timing and availability at prediction time are not documented. |

The current model assigns the highest feature importance to `Tenure` (0.120), followed by `Complain` (0.077). Feature importance indicates model reliance; it does not prove leakage. The available data does not permit a definitive leakage determination.

## Evaluation interpretation

The existing stratified random 80/20 split is a reasonable initial benchmark for distinct customer rows drawn from the same population. Each customer ID occurs once, so there is no repeated-customer group leakage in this split. The split does not demonstrate generalization to a later time period because the workbook has no usable observation timestamp. The reported test metrics should be described as random-holdout performance on this dataset, not future-period performance.

## Required provenance follow-up

Before making a prospective churn claim, obtain or record:

- The exact canonical source URL and complete Liu et al. bibliographic reference intended by the project; the two Kaggle URLs currently recorded in project history conflict and neither is verified as the source of this workbook.
- The source's explicit definition of `Churn`, including any inactivity threshold and label date/horizon.
- The feature observation date/cutoff and feature aggregation windows.
- Confirmation that every input feature is available by the proposed inference time.

If that information cannot be obtained, describe the model as predicting the dataset-provided churn label and state that temporal leakage cannot be ruled out. Do not silently invent a new churn rule or relabel the records.

## References checked

- Historical candidate Kaggle listings (neither verified as the source of this exact workbook):
  - <https://www.kaggle.com/datasets/ankitverma2010/ecommerce-customer-churn-analysis-and-prediction>
  - <https://www.kaggle.com/code/wonderdavid/e-commerce-customer-churn-prediction/data>
- Li, J. (2024), *Customer Churn Prediction using Machine Learning: A Case Study of E-commerce Data*, International Journal of Computer Applications, 186(48): <https://ijcaonline.org/archives/volume186/issue48/customer-churn-prediction-using-machine-learning-a-case-study-of-e-commerce-data/>

These references are retained only to document the conflicting source history. They do not establish the provenance, licensing, operational churn horizon, or feature cutoff of this project copy.
