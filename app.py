from flask import Flask, request, jsonify
import ast
import operator

app = Flask(__name__)

# Safe math operators
operators = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow
}

def safe_eval(expr):
    def eval_node(node):
        if isinstance(node, ast.BinOp):
            return operators[type(node.op)](
                eval_node(node.left),
                eval_node(node.right)
            )
        elif isinstance(node, ast.Num):  # for Python <3.8
            return node.n
        elif isinstance(node, ast.Constant):  # for Python 3.8+
            return node.value
        else:
            raise ValueError("Invalid expression")

    tree = ast.parse(expr, mode="eval")
    return eval_node(tree.body)

@app.route("/test", methods=["GET"])
def test():
    name = request.args.get("name", "")
    return name

@app.route("/calculator", methods=["GET"])
def calculator():
    equation = request.args.get("equation", "")
    try:
        result = safe_eval(equation)
        return str(result)
    except:
        return "Invalid equation", 400

# Required for Vercel
app = app
