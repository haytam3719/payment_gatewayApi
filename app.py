import json
import os
import secrets
from flask import Flask, redirect, request, jsonify, session, url_for
import requests
import square.client
import uuid
import logging

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

request_id = None

@app.route('/')
def home():
    return "Welcome to the Payment Gateway API!"

@app.route('/biller/bills', methods=['POST'])
def receive_bills_data():
    url = "https://biller-api-r47y.onrender.com/bills"
    response = requests.get(url)
    if response.status_code == 200:
        bills_data = response.json()
        print(bills_data)
        return jsonify(bills_data), 200
    else:
        return jsonify({"error": "Failed to fetch bills data from biller API"}), 500

@app.route('/request_payment', methods=['POST'])
def request_payment():
    data = request.json
    bill_id = data.get("id")
    amount = data.get("amount")
    headers = {'Content-Type': 'application/json'}
    biller_api_url = 'https://biller-api-r47y.onrender.com/approve_payment_request'
    payload = {"id": bill_id, "amount": amount}
    print(payload)
    response = requests.post(biller_api_url, json=payload, headers=headers)
    if response.status_code == 200:
        if response.json():
            return jsonify({'success': 'The payment request was accepted'}), response.status_code
        else:
            return jsonify({'error': 'Payment request not approved'}), 403
    else:
        return jsonify({'error': 'An error occurred while processing payment request'}), response.status_code

temp_data_storage = {}

# Square API credentials
CLIENT_ID = 'sandbox-sq0idb-P4f2pTP0-adoQ9zw2oPPpw'
CLIENT_SECRET = 'sandbox-sq0csb-1zNfHrdCVz79YrCuw5WA8M4N4VoMiP7Sjw6nOoWJ6Jw'
REDIRECT_URI = 'https://b69f-196-64-12-157.ngrok-free.app/square_oauth_callback'
AUTHORIZE_URL = 'https://connect.squareupsandbox.com/oauth2/authorize'
TOKEN_URL = 'https://connect.squareupsandbox.com/oauth2/token'

@app.route('/initiate_square_oauth')
def initiate_square_oauth():
    json_str = request.args.get('data')
    request_id = str(uuid.uuid4())
    logging.debug("Generated request ID: %s", request_id)
    try:
        json_data = json.loads(json_str)
        bill_id = json_data.get('bill_id')
        amount = json_data.get('amount')
        request_id = str(uuid.uuid4())
        logging.debug("Generated request ID: %s", request_id)
        try:
            with open("/tmp/temp_data.txt", 'w') as file:
                file.write(f"{request_id},{bill_id},{amount}\n")
            logging.debug("Data written to file successfully.")
        except Exception as e:
            logging.error("Error writing to file: %s", e)
        auth_url = f"{AUTHORIZE_URL}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=MERCHANT_PROFILE_READ PAYMENTS_READ PAYMENTS_WRITE CUSTOMERS_READ"
    except json.JSONDecodeError as e:
        logging.error("Error decoding JSON data: %s", e)
        return jsonify({"error": "Invalid JSON data"}), 400
    return redirect(auth_url)

access_token_storage = {}

@app.route('/square_oauth_callback')
def square_oauth_callback():
    code = request.args.get('code')
    bill_id = None
    amount = None
    try:
        with open("/tmp/temp_data.txt", 'r') as file:
            for line in file:
                stored_request_id, bill_id, amount = line.strip().split(',')
                logging.debug("Values from file: stored_request_id=%s, bill_id=%s, amount=%s", stored_request_id, bill_id, amount)
                break
    except Exception as e:
        logging.error("Error reading from file: %s", e)
    logging.debug("Values after reading from file: stored_request_id=%s, bill_id=%s, amount=%s", stored_request_id, bill_id, amount)
    print(stored_request_id, bill_id, amount)
    if code:
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        response = requests.post(TOKEN_URL, data=data)
        token_data = response.json()
        if 'access_token' in token_data:
            access_token = token_data['access_token']
            access_token_storage[code] = access_token
            redirect_url = url_for('make_payment', code=code, _external=True)
            return redirect(redirect_url)
        else:
            if token_data.get('error') == 'INVALID_SCOPE':
                missing_capabilities = token_data.get('error_description', '').split(': ')[-1]
                error_message = f'Missing capabilities: {missing_capabilities}'
            else:
                error_message = token_data.get('error_description', 'Unknown error')
            return jsonify({'error': error_message}), 400
    else:
        return jsonify({'error': 'Authorization code not found in the request'}), 400

@app.route('/make_payment')
def make_payment():
    authorization_code = request.args.get('code')
    bill_id = None
    amount = None
    try:
        with open("/tmp/temp_data.txt", 'r') as file:
            for line in file:
                stored_request_id, bill_id, amount = line.strip().split(',')
                logging.debug("Values from file: stored_request_id=%s, bill_id=%s, amount=%s", stored_request_id, bill_id, amount)
                break
    except Exception as e:
        logging.error("Error reading from file: %s", e)
    logging.debug("Values after reading from file: stored_request_id=%s, bill_id=%s, amount=%s", stored_request_id, bill_id, amount)
    print(stored_request_id, bill_id, amount)
    print("Query String:", request.query_string)
    print("Bill ID:", bill_id)
    print("Amount:", amount)
    access_token = access_token_storage.get(authorization_code)
    if access_token:
        client = square.client.Client(
            access_token=access_token,
            environment='sandbox'
        )
        sandbox_location_id = 'LY2F0YBN3KQPG'
        idempotency_key = str(uuid.uuid4())
        payment_request = {
            "source_id": "cnon:card-nonce-ok",
            "idempotency_key": idempotency_key,
            "location_id": sandbox_location_id,
            "amount_money": {
                "amount": int(amount) * 100,
                "currency": "USD"
            }
        }
        try:
            result = client.payments.create_payment(body=payment_request)
            if result.is_success():
                headers = {'content-type': 'application/json'}
                payment_id = result.body.get('payment', {}).get('id')
                print(json.dumps({"payment_id": payment_id}))
                response = requests.post("https://biller-api-r47y.onrender.com/payment", json={"bill_id": bill_id, "payment_id": payment_id}, headers=headers)
                print(response.headers)
                return redirect(url_for('merchant_approval', bill_id=bill_id, payment_id=payment_id, _external=True))
            elif result.is_error():
                return jsonify({'error': result.errors}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': 'Access token not found for the provided authorization code'}), 400

@app.route('/merchant_approval', methods=['GET', 'POST'])
def merchant_approval():
    if request.method == 'GET':
        bill_id = request.args.get('bill_id')
        payment_id = request.args.get('payment_id')
        if payment_id:
            return f"GET request received for merchant_approval with payment_id: {payment_id} and bill_id: {bill_id}", 200
        else:
            return "Payment ID not provided in the URL query parameters", 400
    elif request.method == 'POST':
        data = request.json
        bill_id = data.get('bill_id')
        payment_id = data.get('payment_id')
        if payment_id:
            return f"POST request received for merchant_approval with payment_id: {payment_id} and bill_id: {bill_id}", 200
        else:
            return "Payment ID not provided in the POST request", 400
    else:
        return "Method not allowed", 405

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=10001)
