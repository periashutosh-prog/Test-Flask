from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    name = request.args.get("name", "World")
    return jsonify({"message": f"Hello {name}"})

# This is REQUIRED for Vercel
app = app
