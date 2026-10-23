"""Create the bounded private simulator-run table and enable its TTL."""

import os

import boto3
from botocore.exceptions import ClientError

def main() -> None:
    client = boto3.client(
        "dynamodb",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
    table_name = os.getenv(
        "DYNAMODB_SIMULATION_RUNS_TABLE", "diagrammatic_simulation_runs"
    )
    try:
        description = client.describe_table(TableName=table_name)["Table"]
        key_schema = {
            item["AttributeName"]: item["KeyType"]
            for item in description.get("KeySchema", [])
        }
        if key_schema != {"userId": "HASH", "runSlot": "RANGE"}:
            raise RuntimeError(f"{table_name} exists with an incompatible key schema")
        print(f"Using existing {table_name}")
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        client.create_table(
            TableName=table_name,
            KeySchema=[
                {"AttributeName": "userId", "KeyType": "HASH"},
                {"AttributeName": "runSlot", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "userId", "AttributeType": "S"},
                {"AttributeName": "runSlot", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.get_waiter("table_exists").wait(TableName=table_name)
        print(f"Created {table_name}")

    ttl = client.describe_time_to_live(TableName=table_name).get("TimeToLiveDescription", {})
    if ttl.get("TimeToLiveStatus") == "DISABLED":
        client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
        print(f"Enabled TTL on {table_name}.expiresAt")
    elif ttl.get("AttributeName") != "expiresAt":
        raise RuntimeError(
            f"{table_name} TTL is already configured on a different attribute; inspect it before enabling simulator storage"
        )
    elif ttl.get("TimeToLiveStatus") == "DISABLING":
        raise RuntimeError(f"TTL is currently disabling on {table_name}; retry after AWS finishes")
    else:
        print(f"TTL is {ttl.get('TimeToLiveStatus')} on {table_name}.expiresAt")


if __name__ == "__main__":
    main()
