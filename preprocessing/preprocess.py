import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
import joblib


#load dataset


DATA_PATH = "data/raw/ecommerce_customer_churn.xlsx"

df = pd.read_excel(
    DATA_PATH,
    sheet_name="E Comm"
)

print("Original shape:", df.shape)



TARGET = "Churn"
ID_COLUMN = "CustomerID"

X = df.drop(columns=[TARGET, ID_COLUMN])
y = df[TARGET]


#feature types

categorical_features = X.select_dtypes(
    include=["object"]
).columns.tolist()

numerical_features = X.select_dtypes(
    exclude=["object"]
).columns.tolist()

print("\nNumerical features:")
print(numerical_features)

print("\nCategorical features:")
print(categorical_features)


#pipelines
 

numerical_pipeline = Pipeline(
    steps=[
        (
            "imputer",
            SimpleImputer(strategy="median")
        )
    ]
)

categorical_pipeline = Pipeline(
    steps=[
        (
            "imputer",
            SimpleImputer(strategy="most_frequent")
        ),
        (
            "encoder",
            OneHotEncoder(
                handle_unknown="ignore",
                sparse_output=False
            )
        )
    ]
)


preprocessor = ColumnTransformer(
    transformers=[
        (
            "numerical",
            numerical_pipeline,
            numerical_features
        ),
        (
            "categorical",
            categorical_pipeline,
            categorical_features
        )
    ]
)


#train/test split

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42,
    stratify=y
)


print("\nTraining samples:", len(X_train))
print("Testing samples:", len(X_test))

print("\nTraining churn distribution:")
print(y_train.value_counts())

print("\nTesting churn distribution:")
print(y_test.value_counts())


#fit preprocessing ONLY on training data


X_train_processed = preprocessor.fit_transform(X_train)

X_test_processed = preprocessor.transform(X_test)


print("\nProcessed training shape:", X_train_processed.shape)
print("Processed testing shape:", X_test_processed.shape)



feature_names = preprocessor.get_feature_names_out()

print("\nNumber of processed features:", len(feature_names))


#saving

joblib.dump(
    preprocessor,
    "models/preprocessor.pkl"
)

print("\nSaved preprocessing pipeline:")
print("models/preprocessor.pkl")




train_processed = pd.DataFrame(
    X_train_processed,
    columns=feature_names,
    index=X_train.index
)

train_processed[TARGET] = y_train.values

test_processed = pd.DataFrame(
    X_test_processed,
    columns=feature_names,
    index=X_test.index
)

test_processed[TARGET] = y_test.values


train_processed.to_csv(
    "data/processed/train_processed.csv",
    index=False
)

test_processed.to_csv(
    "data/processed/test_processed.csv",
    index=False
)

print("\nSaved:")
print("data/processed/train_processed.csv")
print("data/processed/test_processed.csv")