# Local Installation

This guide covers running the HF Propagation Map on your own machine for development or personal use.

---

## Prerequisites

- Python 3.10 or later (3.12 recommended)
- pip
- An AWS account with DynamoDB access (the app reads and writes DynamoDB even when running locally)

> **Windows note:** Do not use the system Python to run the app if you have multiple Python versions installed. Always use the virtual environment Python as shown below.

---

## 1. Clone the repository

```bash
git clone https://github.com/your-username/propagation.git
cd propagation
```

---

## 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it:

```bash
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
pip install boto3
```

> `boto3` is included here for local use. It is **not** in `requirements.txt` because the Lambda runtime provides it — adding it to the zip would bloat the package unnecessarily.

---

## 4. Configure AWS credentials

The app uses `boto3` to read and write two DynamoDB tables (`hf_solar` and `hf_users`). Your local machine needs AWS credentials with the right permissions.

### Create an IAM user (if you don't have one)

1. AWS Console → **IAM** → **Users** → **Create user**
2. Select **Programmatic access**
3. Attach the inline policy below (or add it after creation via **Add permissions → Create inline policy**)
4. Download the access key CSV — you will not be able to retrieve the secret key again

### IAM policy for local access

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Scan",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "*"
    }
  ]
}
```

> `Scan` and `BatchWriteItem` are required for the solar history pruning logic. Using `"Resource": "*"` avoids ARN-matching issues if table names or regions ever change.

### Configure the AWS CLI

```bash
aws configure
```

Enter your **Access Key ID**, **Secret Access Key**, and **region** (must match where your DynamoDB tables live, e.g. `us-east-1`). Leave output format blank or enter `json`.

Credentials are stored in `~/.aws/credentials` — never commit this file.

---

## 5. Create the DynamoDB tables

If the tables do not exist yet, create them in the AWS Console before running the app. See [AWS\_INSTALL.md — DynamoDB tables](AWS_INSTALL.md#dynamodb-tables) for step-by-step instructions.

---

## 6. Run the development server

```bash
# Windows — always use the venv Python
.\venv\Scripts\python.exe app.py

# macOS / Linux
python app.py
```

Open your browser to **http://127.0.0.1:5000**

---

## What happens on startup

- A background thread starts immediately and fetches fresh solar data, writing it to DynamoDB
- The thread pre-warms the 20m and 40m heatmap cache every 15 minutes
- A Flask development-server warning is printed — this is expected and harmless for local use

---

## Stopping the server

Press `Ctrl+C`. The background thread is a daemon thread and exits automatically.
