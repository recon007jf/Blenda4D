# SPDX-License-Identifier: GPL-3.0-or-later
"""Formula Effector and Formula Field: a typed expression turned into Geometry Nodes math, once, when the object's
group is built. Only numbers, the names in the table the caller gives, + - * / % ** and the functions below are
allowed; anything else is refused with a short message (the expression is never run as Python)."""
import ast
import math

FUNCTIONS = {   # name -> (math node operation, how many arguments)
    "sin": ("SINE", 1), "cos": ("COSINE", 1), "tan": ("TANGENT", 1), "asin": ("ARCSINE", 1), "acos": ("ARCCOSINE", 1),
    "atan": ("ARCTANGENT", 1), "atan2": ("ARCTAN2", 2), "abs": ("ABSOLUTE", 1), "sqrt": ("SQRT", 1),
    "exp": ("EXPONENT", 1), "log": ("LOGARITHM", 2), "floor": ("FLOOR", 1), "ceil": ("CEIL", 1), "round": ("ROUND", 1),
    "fract": ("FRACT", 1), "sign": ("SIGN", 1), "min": ("MINIMUM", 2), "max": ("MAXIMUM", 2), "pow": ("POWER", 2),
    "mod": ("FLOORED_MODULO", 2), "pingpong": ("PINGPONG", 2), "snap": ("SNAP", 2),
}
CONSTANTS = {"pi": math.pi, "e": math.e}
BINARY = {ast.Add: "ADD", ast.Sub: "SUBTRACT", ast.Mult: "MULTIPLY", ast.Div: "DIVIDE", ast.Pow: "POWER",
          ast.Mod: "FLOORED_MODULO"}
COMPARE = {ast.Lt: "LESS_THAN", ast.Gt: "GREATER_THAN"}


class FormulaError(ValueError):
    pass


def check(text, names):
    """None if `text` can be built with these variable names, else a short reason."""
    try:
        _walk(ast.parse(text.strip() or "0", mode="eval").body, set(names), None, {})
    except FormulaError as ex:
        return str(ex)
    except SyntaxError:
        return "This is not a formula (check the brackets and signs)"
    return None


def build(g, text, variables):
    """Math nodes for `text`; variables maps each name to a socket or number. Returns a socket or a number."""
    return _walk(ast.parse(text.strip() or "0", mode="eval").body, set(variables), g, variables)


def _walk(node, names, g, variables):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if node.id not in names:
            raise FormulaError(f"Unknown name: {node.id}")
        return variables.get(node.id, 0.0) if g else 0.0
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _walk(node.operand, names, g, variables)
        if isinstance(node.op, ast.UAdd):
            return v
        return -v if isinstance(v, float) else g.m("MULTIPLY", v, -1.0)
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        a, b = _walk(node.left, names, g, variables), _walk(node.right, names, g, variables)
        return g.m(BINARY[type(node.op)], a, b) if g else 0.0
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE:
        a, b = _walk(node.left, names, g, variables), _walk(node.comparators[0], names, g, variables)
        return g.m(COMPARE[type(node.ops[0])], a, b) if g else 0.0
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        name = node.func.id
        if name == "clamp" and len(node.args) == 1:
            v = _walk(node.args[0], names, g, variables)
            return g.clamp(v) if g else 0.0
        if name not in FUNCTIONS:
            raise FormulaError(f"Unknown function: {name}")
        op, n = FUNCTIONS[name]
        if len(node.args) != n:
            raise FormulaError(f"{name} takes {n} value{'s' if n > 1 else ''}")
        args = [_walk(a, names, g, variables) for a in node.args]
        return g.m(op, *args) if g else 0.0
    raise FormulaError("Only numbers, names, + - * / % ** < > and functions like sin(...) can be used")
