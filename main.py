import re

import mysql.connector
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import db_helper
import generic_helper

app = FastAPI()

inprogress_orders = {}


# Move the global connection to the function for better exception handling
def get_database_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="pass123",
        database="pandeyji_eatery"
    )


@app.post("/")
async def handle_request(request: Request):

    payload = await request.json()
    intent = payload['queryResult']['intent']['displayName']
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult']['outputContexts']
    session_id = generic_helper.extract_session_id(output_contexts[0]['name'])

    intent_handler_dict = {
            'order.add - context: ongoing-order': add_to_order,
            'order.remove - context: ongoing-order' : remove_from_order,
            'order.complete - context: ongoing-order': complete_order,
            'track.order - context: ongoing-tracking': track_order
        }
    return intent_handler_dict[intent](parameters, session_id)

def add_to_order(parameters: dict, session_id: str):
    food_items = parameters["food-item"]
    quantities = parameters["number"]

    if len(food_items) != len(quantities):
        fulfillmentText = "Sorry,Could you please specify the exact quantity"
    else:

        new_food_dict = dict(zip(food_items, quantities))

        if session_id in inprogress_orders:
            current_food_dict = inprogress_orders[session_id]
            current_food_dict.update(new_food_dict)
            inprogress_orders[session_id] = current_food_dict
        else:
            inprogress_orders[session_id] = new_food_dict

        order_str = generic_helper.get_str_from_food_dict(inprogress_orders[session_id])

        fulfillmentText = f"So far you have: {order_str} .Do you need something else"
    return JSONResponse(content={
        "fulfillmentText": fulfillmentText
    })


def complete_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        fulfillment_text = "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
    else:
        order = inprogress_orders[session_id]
        order_id = save_to_db(order)
        if order_id == -1:
            fulfillment_text = "Sorry, I couldn't process your order due to a backend error. " \
                               "Please place a new order again"
        else:
            order_total = db_helper.get_total_order_price(order_id)

            fulfillment_text = f"Awesome. We have placed your order. " \
                               f"Here is your order id # {order_id}. " \
                               f"Your order total is {order_total} which you can pay at the time of delivery!"

        del inprogress_orders[session_id]

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


def save_to_db(order: dict):
    next_order_id = db_helper.get_next_order_id()

    # Insert individual items along with quantity in orders table
    for food_item, quantity in order.items():
        rcode = db_helper.insert_order_item(
            food_item,
            quantity,
            next_order_id
        )

        if rcode == -1:
            return -1

    # Now insert order tracking status
    db_helper.insert_order_tracking(next_order_id, "in progress")

    return next_order_id


def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having trouble finding the order. Sorry, can you place an order?"
        })

    current_order = inprogress_orders[session_id]
    food_items = parameters["food-item"]
    removed_items = []
    no_such_items = []

    for item in food_items:
        if item not in current_order:
            no_such_items.append(item)
        else:
            removed_items.append(item)
            del current_order[item]

    fulfillment_text = ""

    if removed_items:
        fulfillment_text += f"Removed {', '.join(removed_items)} from your order! "

    if no_such_items:
        fulfillment_text += f"Your current order does not have {', '.join(no_such_items)}. "

    if not current_order:
        fulfillment_text += "Your order is empty"
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text += f"Here is what is left in your order: {order_str}"

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


def track_order(parameters: dict, session_id: str):
    order_id_param = parameters.get('order_id')

    if order_id_param:
        try:
            order_id = int(order_id_param)
        except ValueError:
            return JSONResponse(content={
                "fulfillmentText": "Invalid order id provided."
            })

        try:
            cnx = get_database_connection()
            cursor = cnx.cursor()

            query = "SELECT status FROM order_tracking WHERE `order_id` = %s"
            cursor.execute(query, (order_id,))

            result = cursor.fetchone()

            cursor.close()
            cnx.close()

            if result:
                fulfillment_text = f"The order status for order id {order_id} is: {result[0]}"
            else:
                fulfillment_text = f"No order found with order id {order_id}"

            return JSONResponse(content={
                "fulfillmentText": fulfillment_text
            })

        except Exception as e:
            return JSONResponse(content={
                "fulfillmentText": f"An error occurred while processing the request. {str(e)}"
            })
    else:
        return JSONResponse(content={
            "fulfillmentText": "No order id provided."
        })
