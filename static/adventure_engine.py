"""
Code Quest's text-adventure engine -- a second coding vehicle
alongside turtle. Imported for real (`import adventure as world`),
not injected as hidden boilerplate, so the kid's own code keeps its
own line numbers in any traceback. Uses the real `turtle` module
internally to draw an auto-map on the same canvas turtle tasks use.
"""
import turtle

_rooms = {}
_pos = None
_visited = set()
_inventory = []
_positions = {}
_pen = None
_avatar = None

_DIRS = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}
_CELL = 90
_SIZE = 60


def room(name, desc, exits=None, items=None):
    """Declare a room. Call this for every room before start_at()."""
    _rooms[name] = {"desc": desc, "exits": exits or {}, "items": list(items or [])}


def start_at(name):
    global _pos, _pen, _avatar
    if name not in _rooms:
        print("There's no room called " + repr(name) + ". "
              "Pass the exact name you gave it in world.room(...), as text in quotes.")
        return
    _pos = name
    _visited.add(name)
    _pen = turtle.Turtle()
    _pen.hideturtle()
    _pen.speed(0)
    _pen.penup()
    _avatar = turtle.Turtle()
    _avatar.shape("turtle")
    _avatar.penup()
    _avatar.speed(0)
    _compute_positions()
    _redraw()
    look()


def look():
    r = _rooms[_pos]
    print(r["desc"])
    if r["items"]:
        print("You see: " + ", ".join(r["items"]))


def go(direction):
    global _pos
    exits = _rooms[_pos]["exits"]
    if direction not in exits:
        print("You can't go that way.")
        return
    target = exits[direction]
    if target not in _rooms:
        print("The exit " + repr(direction) + " points to " + repr(target) +
              ", but you never declared that room with world.room(...).")
        return
    _pos = target
    _visited.add(_pos)
    _redraw()
    print("You went " + direction + " to " + _pos + ".")
    look()


def take(item):
    r = _rooms[_pos]
    if item not in r["items"]:
        print("There's no " + item + " here.")
        return
    r["items"].remove(item)
    _inventory.append(item)
    print("You picked up: " + item)


def inventory():
    print("You are carrying: " + (", ".join(_inventory) if _inventory else "nothing"))
    return list(_inventory)


def neighbors(name):
    """Room names directly reachable from `name` -- for writing your
    own search over the map (e.g. a recursive maze solver)."""
    if name not in _rooms:
        print("There's no room called " + repr(name) + " -- treating it as a dead end.")
        return []
    return list(_rooms[name]["exits"].values())


def _compute_positions():
    global _positions
    _positions = {_pos: (0, 0)}
    frontier = [_pos]
    while frontier:
        nxt = []
        for r in frontier:
            gx, gy = _positions[r]
            # An exit can point to a room name that was never declared
            # with world.room(...) -- skip it here (go() prints a
            # friendly message if the kid actually tries to walk there)
            # rather than crashing the whole layout pass on a typo.
            for d, target in _rooms[r]["exits"].items():
                if target in _positions or d not in _DIRS or target not in _rooms:
                    continue
                dx, dy = _DIRS[d]
                _positions[target] = (gx + dx, gy + dy)
                nxt.append(target)
        frontier = nxt


def _draw_room(name, gx, gy, current):
    x, y = gx * _CELL, gy * _CELL
    _pen.goto(x - _SIZE / 2, y - _SIZE / 2)
    _pen.pendown()
    _pen.pencolor("black")
    _pen.fillcolor("#5EEAD4" if current else "#E2E8F0")
    _pen.begin_fill()
    for _ in range(4):
        _pen.forward(_SIZE)
        _pen.left(90)
    _pen.end_fill()
    _pen.penup()
    _pen.goto(x, y - 8)
    _pen.fillcolor("black")  # write() renders in fillcolor, not pencolor
    _pen.write(name, align="center", font=("Arial", 9, "normal"))


def _draw_edge(x1, y1, x2, y2):
    _pen.goto(x1, y1)
    _pen.pendown()
    _pen.goto(x2, y2)
    _pen.penup()


def _redraw():
    _pen.clear()
    drawn = set()
    for name in _visited:
        gx, gy = _positions[name]
        for d, target in _rooms[name]["exits"].items():
            if target in _visited and d in _DIRS:
                key = tuple(sorted([name, target]))
                if key in drawn:
                    continue
                drawn.add(key)
                tx, ty = _positions[target]
                _draw_edge(gx * _CELL, gy * _CELL, tx * _CELL, ty * _CELL)
    for name in _visited:
        gx, gy = _positions[name]
        _draw_room(name, gx, gy, name == _pos)
    ax, ay = _positions[_pos]
    _avatar.goto(ax * _CELL, ay * _CELL + _SIZE)
