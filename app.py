from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    name = request.args.get("name", "World")
    return jsonify({
        "message": f"Hello {name}"
    })

# Required for Vercel
def handler(request, context):
    return app(request.environ, lambda *args: None)
