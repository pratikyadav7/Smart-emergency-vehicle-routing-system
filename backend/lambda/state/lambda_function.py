def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": '{"status": "ok", "message": "Emergency Green Corridor backend is running"}'
    }