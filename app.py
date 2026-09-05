"""
Code Quest backend — Flask + SQLite (Turso), multi-family.

Single process serves both the frontend (static/index.html) and the JSON
API. Parents authenticate via Google OAuth; kids authenticate via a
per-kid generated handle + short PIN. Every request that touches
kid/task/submission/redemption/settings data resolves `family_id` from
the session (never from a client-supplied value) and every route that
reads or writes a specific record verifies that record actually belongs
to that family before acting.

Run with:  python app.py
Then visit http://<this-machine's-LAN-IP>:5000 from any device on the
same network (or the deployed Render URL).
"""

import json
import os
import random
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Flask, g, jsonify, redirect, request, send_from_directory, session, url_for

import db as dbmod

app = Flask(__name__, static_folder="static", static_url_path="")

ON_RENDER = os.environ.get("RENDER") == "true"

app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or (
    # Fail loudly in production rather than silently running with a
    # guessable key; fine to fall back for quick local testing only.
    (_ for _ in ()).throw(RuntimeError("FLASK_SECRET_KEY must be set on Render"))
    if ON_RENDER else "dev-only-insecure-key-do-not-use-in-production"
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = ON_RENDER
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

DEFAULT_SETTINGS = {"pointsPerMinute": "1", "dailyCapMinutes": "60"}

# Canonical starter content cloned (with freshly generated ids) into any
# newly created kid's own task list — see seed_starter_tasks_for_kid().
# Never reused as literal ids: two different kids each get their own
# independent copy of these rows.
STARTER_TURTLE_TASKS = [
    ("Draw Your Initials", 10, "easy",
     "Draw your initials using only forward, right, left, penup, and pendown. No loops required — but you might find you want one.",
     ["shapes"]),
    ("Any-Sided Shape", 10, "easy",
     "Write code that can draw a triangle, pentagon, hexagon — any shape — by changing just one number. Figure out the relationship between number of sides and turn angle.",
     ["shapes", "loops_basic"]),
    ("Draw a House", 10, "easy",
     "Combine a square and a triangle to draw a simple house shape — walls plus a roof, in one continuous drawing.",
     ["shapes"]),
    ("Rainbow Line", 10, "easy",
     "Draw a series of lines side by side, each a different color, using a loop and t.color().",
     ["colors", "loops_basic"]),
    ("Smiley Face", 10, "easy",
     "Use t.circle() plus penup/pendown to draw a face — one big circle, two small circles for eyes, a curved mouth.",
     ["shapes"]),
    ("Nested Squares", 10, "easy",
     "Draw several squares of increasing size, one inside the other, using a single loop where the side length grows each time.",
     ["shapes", "loops_basic"]),
    ("Flower with Circles", 10, "easy",
     "Draw several overlapping circles arranged in a ring, using a loop that turns the turtle a bit before drawing each circle.",
     ["shapes", "loops_basic"]),
    ("Draw Your Number", 10, "easy",
     "Pick a number that means something to you (your age, your hockey jersey number) and draw it big using lines and curves.",
     ["shapes"]),
    ("Dotted Path", 10, "easy",
     "Use t.dot() inside a loop to draw a dashed or dotted line or shape instead of a solid one.",
     ["loops_basic"]),
    ("Maze Border", 10, "easy",
     "Draw a rectangle border big enough to be a maze outline, and mark the starting corner with a dot.",
     ["shapes"]),
    ("Growing Spiral", 20, "medium",
     "Draw a spiral where each side is longer than the last. You'll need a loop where the forward distance changes each time through.",
     ["loops_basic"]),
    ("Checkerboard Grid", 20, "medium",
     "Draw an 8x8 grid of squares, alternating filled and unfilled. This needs a loop inside a loop.",
     ["nested_loops"]),
    ("Random Walk", 20, "medium",
     "Make the turtle take 50 random steps in random directions using the random module. Bonus: change color as it goes.",
     ["randomness", "loops_basic"]),
    ("Five-Pointed Star", 20, "medium",
     "Draw a five-pointed star without lifting the pen — one loop, one clever turn angle. Hunt for the angle yourself before looking it up.",
     ["loops_basic"]),
    ("Traffic Light Simulator", 30, "hard",
     "Draw three circles (red, yellow, green). Using time.sleep(), light up one at a time in sequence by filling it in.",
     ["functions"]),
    ("Recursive Tree", 30, "hard",
     "Draw a branching tree using a function that calls itself. Ask an AI to explain recursion conceptually first, then build it yourself.",
     ["recursion", "functions"]),
    ("Keyboard Etch-a-Sketch", 30, "hard",
     "Arrow keys move the turtle, spacebar changes color, a key clears the screen. Real interactivity, not just run-once.",
     ["event_handling"]),
    ("Design Your Own", 30, "hard",
     "Pick something you want the turtle to draw or do. Break it into steps yourself before writing any code.",
     []),
    ("Zigzag Path", 10, "easy",
     "Draw a zigzag line by alternating turning right and left inside a loop, moving forward a bit each time.",
     ["loops_basic"]),
    ("Polka Dot Row", 10, "easy",
     "Use t.dot() inside a loop to draw a neat row of evenly-spaced dots, moving forward between each one.",
     ["loops_basic"]),
    ("Simple Arrow", 10, "easy",
     "Draw an arrow — a straight shaft with a small triangular head — using only forward, right, and left.",
     ["shapes"]),
    ("Color Blocks", 10, "easy",
     "Draw four filled squares in a row, each a different color, using begin_fill() and end_fill().",
     ["colors", "shapes"]),
    ("Star Necklace", 10, "easy",
     "Draw a row of small five-pointed stars strung along an invisible line — pen up to move between each one.",
     ["shapes", "loops_basic"]),
    ("Picture Frame", 10, "easy",
     "Draw a rectangle, then a smaller rectangle inside it, so it looks like a picture frame.",
     ["shapes"]),
    ("Sunburst Lines", 10, "easy",
     "Draw 12 lines radiating out from the center point like sun rays, using a loop that turns the same angle each time.",
     ["loops_basic"]),
    ("Traffic Cone", 10, "easy",
     "Draw a triangle on top of a small rectangle base, colored orange, to look like a traffic cone.",
     ["shapes", "colors"]),
    ("Your Initials, Twice", 10, "easy",
     "Draw your first and last initial side by side, reusing the same drawing code for both if you can.",
     ["shapes"]),
    ("Bullseye Target", 10, "easy",
     "Draw four circles of the same center point but different sizes, alternating between two colors, like an archery target.",
     ["shapes", "colors", "loops_basic"]),
    ("Color-Alternating Fence", 20, "medium",
     "Draw a row of fence posts, alternating between two colors using an if/else inside your loop based on whether the post number is even or odd.",
     ["colors", "loops_basic", "conditionals"]),
    ("Grid of Dots", 20, "medium",
     "Draw an NxN grid of dots using a loop inside a loop — the outer loop for rows, the inner loop for columns.",
     ["nested_loops"]),
    ("Random Confetti", 20, "medium",
     "Scatter 100 small dots of random colors at random positions on the screen using the random module.",
     ["randomness"]),
    ("Reusable Flower Function", 20, "medium",
     "Write a function draw_flower(size) that draws one flower, then call it three times at different spots to plant a small garden.",
     ["functions", "shapes"]),
    ("Rainbow Nested Squares", 20, "medium",
     "Draw several squares nested inside each other like Nested Squares, but give each one the next color from a list as you go.",
     ["nested_loops", "colors"]),
    ("Recursive Snowflake", 30, "hard",
     "Write a function that draws a jagged snowflake edge by calling itself with a smaller size each time, stopping at a small base-case size.",
     ["recursion", "functions"]),
    ("Turtle Race Game", 30, "hard",
     "Two turtles start at the same line. Each turn, move each one forward a random amount; stop and print the winner once one crosses a finish line.",
     ["randomness", "conditionals", "loops_basic"]),
    ("Click-to-Draw", 30, "hard",
     "Use turtle's onscreenclick so that clicking anywhere on the canvas draws a dot there — build a picture just by clicking around.",
     ["event_handling"]),
    ("Guarded Drawing", 30, "hard",
     "Write a function that only draws a shape if a variable you set in your code matches a specific value — otherwise it does nothing.",
     ["functions", "conditionals"]),
    ("Star Generator Function", 30, "hard",
     "Write a function star(n) that can draw a star with ANY number of points by figuring out the correct turn angle inside the function itself.",
     ["functions", "loops_basic"]),
]

STARTER_JUDGE_TASKS = [
    ("Even or Odd", 10, "easy",
     "Read a whole number from input() and print \"even\" if it's even, or \"odd\" if it's odd.",
     ["conditionals"],
     [{"input": ["4"], "expected": "even"}, {"input": ["7"], "expected": "odd"}, {"input": ["0"], "expected": "even"}]),
    ("FizzBuzz", 20, "medium",
     "Read a whole number n from input(). For each number from 1 to n, print the number -- but print \"Fizz\" instead if it's divisible by 3, \"Buzz\" if it's divisible by 5, and \"FizzBuzz\" if it's divisible by both.",
     ["loops_basic", "conditionals"],
     [{"input": ["15"], "expected": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz"}]),
    ("Staircase Ways", 35, "hard",
     "Read a whole number n -- the number of stairs. You can climb 1 or 2 stairs at a time. Print how many different ways there are to reach the top. (A plain recursive solution works for small n, but gets very slow for bigger ones -- memoization is what makes it fast for any input.)",
     ["recursion", "dynamic_programming"],
     [{"input": ["1"], "expected": "1"}, {"input": ["5"], "expected": "8"}, {"input": ["10"], "expected": "89"}, {"input": ["15"], "expected": "987"}]),
]

STARTER_FUNDAMENTALS_TASKS = [
    ("Say Hello", 3, "fundamentals",
     "Read your name from input(), store it in a variable, and print \"Hello, \" followed by your name.",
     ["variables"],
     [{"input": ["Shayne"], "expected": "Hello, Shayne"}, {"input": ["Kelly"], "expected": "Hello, Kelly"}, {"input": ["Ada"], "expected": "Hello, Ada"}]),
    ("Text or Number?", 3, "fundamentals",
     "Read a number from input() and print it doubled. Remember: input() always gives you text -- wrap it in int() to treat it as a real number.",
     ["type_casting"],
     [{"input": ["5"], "expected": "10"}, {"input": ["0"], "expected": "0"}, {"input": ["-4"], "expected": "-8"}]),
    ("Count to Ten", 3, "fundamentals",
     "Print the numbers 1 through 10, one per line.",
     ["loops_basic"],
     [{"input": [], "expected": "1\n2\n3\n4\n5\n6\n7\n8\n9\n10"}]),
    ("Sum Three Numbers", 3, "fundamentals",
     "Read 3 numbers from input() (one per line), store them in a list, and print their sum.",
     ["lists"],
     [{"input": ["1", "2", "3"], "expected": "6"}, {"input": ["10", "20", "5"], "expected": "35"}]),
    ("Shout Three Times", 3, "fundamentals",
     "Write a function called shout that prints \"HELLO!\". Call your function 3 times.",
     ["functions"],
     [{"input": [], "expected": "HELLO!\nHELLO!\nHELLO!"}]),
    ("Double It", 3, "fundamentals",
     "Write a function called double that takes one parameter and returns it multiplied by 2. Read a number from input(), call double() on it, and print the result.",
     ["parameters"],
     [{"input": ["4"], "expected": "8"}, {"input": ["10"], "expected": "20"}, {"input": ["0"], "expected": "0"}]),
    ("Store and Reuse", 3, "fundamentals",
     "Read a word from input(), store it in a variable, then print that word three times, once per line -- using the variable each time (not typing the word again).",
     ["variables"],
     [{"input": ["cat"], "expected": "cat\ncat\ncat"}, {"input": ["Shayne"], "expected": "Shayne\nShayne\nShayne"}]),
    ("Countdown", 3, "fundamentals",
     "Read a whole number n from input() and print the numbers from n down to 1, one per line, using a loop.",
     ["loops_basic"],
     [{"input": ["5"], "expected": "5\n4\n3\n2\n1"}, {"input": ["3"], "expected": "3\n2\n1"}]),
    ("Sum With a Loop", 3, "fundamentals",
     "Read a whole number n from input(). Using a loop (not the sum() function), add up all the numbers from 1 to n and print the total.",
     ["loops_basic"],
     [{"input": ["5"], "expected": "15"}, {"input": ["10"], "expected": "55"}, {"input": ["1"], "expected": "1"}]),
    ("Biggest of Three", 3, "fundamentals",
     "Read 3 numbers from input() (one per line), store them in a list, and print the largest one using max().",
     ["lists"],
     [{"input": ["3", "9", "5"], "expected": "9"}, {"input": ["10", "2", "7"], "expected": "10"}]),
    ("Function Reuse", 3, "fundamentals",
     "Write a function called line that prints \"-----\". Call your function 5 times to print 5 lines.",
     ["functions"],
     [{"input": [], "expected": "-----\n-----\n-----\n-----\n-----"}]),
    ("Add Two Numbers", 3, "fundamentals",
     "Write a function called add_two that takes two parameters and returns their sum. Read two numbers from input() (one per line), call add_two() on them, and print the result.",
     ["parameters"],
     [{"input": ["3", "4"], "expected": "7"}, {"input": ["10", "-2"], "expected": "8"}, {"input": ["0", "0"], "expected": "0"}]),
    ("Remainder Check", 3, "fundamentals",
     "Read a whole number from input() and print the remainder when it's divided by 3, using the % operator.",
     ["simple_math"],
     [{"input": ["10"], "expected": "1"}, {"input": ["9"], "expected": "0"}, {"input": ["14"], "expected": "2"}]),
    ("Average of Two", 3, "fundamentals",
     "Read two numbers from input() (one per line) and print their average.",
     ["simple_math"],
     [{"input": ["4", "6"], "expected": "5.0"}, {"input": ["10", "5"], "expected": "7.5"}, {"input": ["0", "0"], "expected": "0.0"}]),
    ("Seeded Random Number", 3, "fundamentals",
     "Import random. Read a whole number from input() and use it as a seed with random.seed(). Then print the result of random.randint(1, 10). Using the same seed always produces the same result -- that's what makes this testable!",
     ["random_library"],
     [{"input": ["1"], "expected": "5"}, {"input": ["7"], "expected": "1"}, {"input": ["42"], "expected": "4"}]),
    ("Seeded Random Choice", 3, "fundamentals",
     "Import random. Read a whole number from input() and use it as a seed with random.seed(). Create a list of words: [\"apple\", \"banana\", \"cherry\", \"date\"]. Print the result of random.choice() on that list.",
     ["random_library"],
     [{"input": ["2"], "expected": "banana"}, {"input": ["5"], "expected": "apple"}, {"input": ["8"], "expected": "date"}]),
    ("Favorite Color", 3, "fundamentals",
     "Read a color from input(), store it in a variable, and print \"My favorite color is \" followed by it.",
     ["variables"],
     [{"input": ["red"], "expected": "My favorite color is red"}, {"input": ["blue"], "expected": "My favorite color is blue"}]),
    ("Store Your Age", 3, "fundamentals",
     "Read your age from input(), store it in a variable, and print what your age will be next year.",
     ["variables"],
     [{"input": ["10"], "expected": "Next year I will be 11"}, {"input": ["5"], "expected": "Next year I will be 6"}]),
    ("Swap Two Words", 3, "fundamentals",
     "Read two words from input() (one per line) and print them swapped, second word first, separated by a space.",
     ["variables"],
     [{"input": ["cat", "dog"], "expected": "dog cat"}, {"input": ["up", "down"], "expected": "down up"}]),
    ("Full Name", 3, "fundamentals",
     "Read a first name, then a last name, and print \"Hello, \" followed by the full name.",
     ["variables"],
     [{"input": ["Ada", "Lovelace"], "expected": "Hello, Ada Lovelace"}]),
    ("Temperature Label", 3, "fundamentals",
     "Read a number from input(), store it in a variable, and print it followed by \" degrees\".",
     ["variables"],
     [{"input": ["72"], "expected": "72 degrees"}, {"input": ["100"], "expected": "100 degrees"}]),
    ("Store Then Change", 3, "fundamentals",
     "Read a number, store it in a variable, add 10 to that same variable, then print it.",
     ["variables"],
     [{"input": ["5"], "expected": "15"}, {"input": ["0"], "expected": "10"}, {"input": ["-3"], "expected": "7"}]),
    ("Reassign It", 3, "fundamentals",
     "Read a word into a variable, then reassign that same variable to the word \"banana\", and print it.",
     ["variables"],
     [{"input": ["apple"], "expected": "banana"}, {"input": ["anything"], "expected": "banana"}]),
    ("Count the Letters", 3, "fundamentals",
     "Read a word from input(), store its length in a variable using len(), and print it.",
     ["variables"],
     [{"input": ["cat"], "expected": "3"}, {"input": ["hello"], "expected": "5"}]),
    ("Nickname Tag", 3, "fundamentals",
     "Read a name into a variable and print \"Hi \" followed by the name followed by \"!!!\".",
     ["variables"],
     [{"input": ["Sam"], "expected": "Hi Sam!!!"}]),
    ("Total in a Variable", 3, "fundamentals",
     "Read two numbers, add them into a variable called total, and print total.",
     ["variables"],
     [{"input": ["3", "4"], "expected": "7"}, {"input": ["10", "-2"], "expected": "8"}]),
    ("Price Tag", 3, "fundamentals",
     "Read a price into a variable and print a dollar sign followed by it.",
     ["variables"],
     [{"input": ["5"], "expected": "$5"}, {"input": ["19"], "expected": "$19"}]),
    ("Add As Numbers", 3, "fundamentals",
     "Read two numbers from input() and print their sum -- remember input() gives you text, so cast with int() first.",
     ["type_casting"],
     [{"input": ["2", "3"], "expected": "5"}, {"input": ["10", "20"], "expected": "30"}]),
    ("Float It", 3, "fundamentals",
     "Read a number from input(), cast it with float(), and print it doubled.",
     ["type_casting"],
     [{"input": ["3"], "expected": "6.0"}, {"input": ["2.5"], "expected": "5.0"}]),
    ("String of a Number", 3, "fundamentals",
     "Read a number, cast it to int(), then use str() to combine it with a text label and print it.",
     ["type_casting"],
     [{"input": ["7"], "expected": "Value: 7"}, {"input": ["42"], "expected": "Value: 42"}]),
    ("Whole Number Only", 3, "fundamentals",
     "Read a decimal number from input() and print just the whole-number part (cast to float, then to int).",
     ["type_casting"],
     [{"input": ["3.9"], "expected": "3"}, {"input": ["7.1"], "expected": "7"}]),
    ("Compare Two Numbers", 3, "fundamentals",
     "Read two numbers as int() and print \"bigger\" if the first is bigger than the second, otherwise \"smaller or equal\".",
     ["type_casting"],
     [{"input": ["5", "3"], "expected": "bigger"}, {"input": ["2", "8"], "expected": "smaller or equal"}]),
    ("Triple It (Casting)", 3, "fundamentals",
     "Read a number, cast it to int(), and print it multiplied by 3.",
     ["type_casting"],
     [{"input": ["4"], "expected": "12"}, {"input": ["0"], "expected": "0"}]),
    ("You Entered It", 3, "fundamentals",
     "Read a number, cast it to int(), then use str() to print \"You entered \" followed by the number.",
     ["type_casting"],
     [{"input": ["9"], "expected": "You entered 9"}, {"input": ["100"], "expected": "You entered 100"}]),
    ("Divide Evenly", 3, "fundamentals",
     "Read two whole numbers and print the result of dividing them with // (integer division, no decimal).",
     ["type_casting"],
     [{"input": ["10", "3"], "expected": "3"}, {"input": ["9", "3"], "expected": "3"}, {"input": ["7", "2"], "expected": "3"}]),
    ("Percent as Number", 3, "fundamentals",
     "Read a whole number representing a percent and print it divided by 100.",
     ["type_casting"],
     [{"input": ["50"], "expected": "0.5"}, {"input": ["25"], "expected": "0.25"}]),
    ("Age in Months", 3, "fundamentals",
     "Read an age in years (may have a decimal) as float() and print it multiplied by 12.",
     ["type_casting"],
     [{"input": ["2"], "expected": "24.0"}, {"input": ["0.5"], "expected": "6.0"}]),
    ("Convert and Compare to Zero", 3, "fundamentals",
     "Read a number as int() and print \"positive\" if it's greater than 0, otherwise \"not positive\".",
     ["type_casting"],
     [{"input": ["5"], "expected": "positive"}, {"input": ["-3"], "expected": "not positive"}, {"input": ["0"], "expected": "not positive"}]),
    ("Even Numbers Up To N", 3, "fundamentals",
     "Read a whole number n and print every even number from 2 up to n, one per line.",
     ["loops_basic"],
     [{"input": ["10"], "expected": "2\n4\n6\n8\n10"}, {"input": ["6"], "expected": "2\n4\n6"}]),
    ("Multiplication Table", 3, "fundamentals",
     "Read a number n and print n times 1 through n times 5, one per line.",
     ["loops_basic"],
     [{"input": ["3"], "expected": "3\n6\n9\n12\n15"}, {"input": ["2"], "expected": "2\n4\n6\n8\n10"}]),
    ("Repeat a Word", 3, "fundamentals",
     "Read a word, then read a count, and print the word that many times, one per line.",
     ["loops_basic"],
     [{"input": ["hi", "3"], "expected": "hi\nhi\nhi"}, {"input": ["go", "1"], "expected": "go"}]),
    ("Sum of Squares", 3, "fundamentals",
     "Read a whole number n and print the sum of the squares of 1 through n, using a loop.",
     ["loops_basic"],
     [{"input": ["3"], "expected": "14"}, {"input": ["1"], "expected": "1"}, {"input": ["4"], "expected": "30"}]),
    ("Count Down By Twos", 3, "fundamentals",
     "Read an even number n and count down to 0 by twos, one number per line.",
     ["loops_basic"],
     [{"input": ["6"], "expected": "6\n4\n2\n0"}, {"input": ["4"], "expected": "4\n2\n0"}]),
    ("Stars in a Row", 3, "fundamentals",
     "Read a whole number n and print a single line made of n asterisks, built up inside a loop.",
     ["loops_basic"],
     [{"input": ["5"], "expected": "*****"}, {"input": ["3"], "expected": "***"}]),
    ("While Countdown", 3, "fundamentals",
     "Read a whole number n and use a while loop to count down from n to 1, one per line.",
     ["loops_basic"],
     [{"input": ["3"], "expected": "3\n2\n1"}, {"input": ["1"], "expected": "1"}]),
    ("Largest So Far", 3, "fundamentals",
     "Read 5 numbers, one per line, and print the largest one -- track it in a variable as you go, without using max().",
     ["loops_basic"],
     [{"input": ["3", "9", "1", "4", "2"], "expected": "9"}, {"input": ["5", "5", "5", "5", "5"], "expected": "5"}]),
    ("Skip By Threes", 3, "fundamentals",
     "Read a whole number n and print every multiple of 3 from 3 up to n, one per line.",
     ["loops_basic"],
     [{"input": ["9"], "expected": "3\n6\n9"}, {"input": ["10"], "expected": "3\n6\n9"}]),
    ("Count Matches", 3, "fundamentals",
     "Read a whole number n, then read n words one per line, and print how many of them are exactly \"yes\".",
     ["loops_basic"],
     [{"input": ["3", "yes", "no", "yes"], "expected": "2"}, {"input": ["2", "no", "no"], "expected": "0"}]),
    ("Running Total Printed Each Step", 3, "fundamentals",
     "Read a whole number n and print the running total after adding each number from 1 to n.",
     ["loops_basic"],
     [{"input": ["3"], "expected": "1\n3\n6"}, {"input": ["4"], "expected": "1\n3\n6\n10"}]),
    ("Smallest of Three", 3, "fundamentals",
     "Read 3 numbers, store them in a list, and print the smallest one using min().",
     ["lists"],
     [{"input": ["3", "9", "5"], "expected": "3"}, {"input": ["10", "2", "7"], "expected": "2"}]),
    ("Average of a List", 3, "fundamentals",
     "Read 3 numbers into a list and print their average using sum() and len().",
     ["lists"],
     [{"input": ["3", "6", "9"], "expected": "6.0"}, {"input": ["10", "20", "30"], "expected": "20.0"}]),
    ("Second Item", 3, "fundamentals",
     "Read 3 words into a list and print the second one (index 1).",
     ["lists"],
     [{"input": ["cat", "dog", "fish"], "expected": "dog"}]),
    ("Last Item", 3, "fundamentals",
     "Read 3 numbers into a list and print the last one using index -1.",
     ["lists"],
     [{"input": ["1", "2", "3"], "expected": "3"}, {"input": ["7", "8", "9"], "expected": "9"}]),
    ("Build a List With a Loop", 3, "fundamentals",
     "Read a whole number n, then read n numbers one per line, appending each to a list, and print the list's length.",
     ["lists"],
     [{"input": ["3", "1", "2", "3"], "expected": "3"}, {"input": ["2", "5", "6"], "expected": "2"}]),
    ("Sum a Growing List", 3, "fundamentals",
     "Read a whole number n, then read n numbers appending each to a list with a loop, and print their sum.",
     ["lists"],
     [{"input": ["3", "1", "2", "3"], "expected": "6"}, {"input": ["2", "10", "20"], "expected": "30"}]),
    ("Count in a List", 3, "fundamentals",
     "Given the list [1, 2, 2, 3, 2], read a target number and print how many times it appears in the list.",
     ["lists"],
     [{"input": ["2"], "expected": "3"}, {"input": ["1"], "expected": "1"}, {"input": ["5"], "expected": "0"}]),
    ("List of Squares", 3, "fundamentals",
     "Read a whole number n, build a list of the squares of 1 through n, then print each one on its own line.",
     ["lists"],
     [{"input": ["3"], "expected": "1\n4\n9"}, {"input": ["4"], "expected": "1\n4\n9\n16"}]),
    ("First and Last", 3, "fundamentals",
     "Read 3 numbers into a list and print the first one plus the last one.",
     ["lists"],
     [{"input": ["1", "2", "3"], "expected": "4"}, {"input": ["10", "5", "1"], "expected": "11"}]),
    ("Reverse Print", 3, "fundamentals",
     "Read 3 words into a list and print them in reverse order, one per line.",
     ["lists"],
     [{"input": ["one", "two", "three"], "expected": "three\ntwo\none"}]),
    ("Is It In The List", 3, "fundamentals",
     "Given a fixed list of fruits, read a word and print \"yes\" if it's in the list, otherwise \"no\".",
     ["lists"],
     [{"input": ["banana"], "expected": "yes"}, {"input": ["grape"], "expected": "no"}]),
    ("Say Goodbye", 3, "fundamentals",
     "Write a function called bye that prints \"Goodbye!\". Call it twice.",
     ["functions"],
     [{"input": [], "expected": "Goodbye!\nGoodbye!"}]),
    ("Print a Border", 3, "fundamentals",
     "Write a function called border that prints a line of equal signs. Call it, print \"Title\", then call it again.",
     ["functions"],
     [{"input": [], "expected": "========\nTitle\n========"}]),
    ("Function Calling Function", 3, "fundamentals",
     "Write a function a that prints \"A\", and a function b that calls a() and then prints \"B\". Call b().",
     ["functions"],
     [{"input": [], "expected": "A\nB"}]),
    ("Count with a Function", 3, "fundamentals",
     "Write a function called count_to_three that prints 1, 2, 3 (one per line) using a loop inside it. Call it.",
     ["functions"],
     [{"input": [], "expected": "1\n2\n3"}]),
    ("Return a Value", 3, "fundamentals",
     "Write a function called five that returns 5. Print the result of calling it twice and adding the results together.",
     ["functions"],
     [{"input": [], "expected": "10"}]),
    ("Greet Function No Args", 3, "fundamentals",
     "Write a function called greet that prints \"Hello there!\". Read a number and call greet() that many times.",
     ["functions"],
     [{"input": ["2"], "expected": "Hello there!\nHello there!"}, {"input": ["1"], "expected": "Hello there!"}]),
    ("Function Returns Then Used", 3, "fundamentals",
     "Write a function called square that returns 4 times 4. Print the result of calling it, minus 1.",
     ["functions"],
     [{"input": [], "expected": "15"}]),
    ("Two Functions, One Output", 3, "fundamentals",
     "Write two functions, line1 and line2, each printing a different line of text. Call line1() then line2().",
     ["functions"],
     [{"input": [], "expected": "Line one\nLine two"}]),
    ("Function With a Loop and Return", 3, "fundamentals",
     "Write a function called total_to_five that adds up 1 through 5 with a loop and returns the total. Print the result.",
     ["functions"],
     [{"input": [], "expected": "15"}]),
    ("Call It Twice Or Once", 3, "fundamentals",
     "Write a function called hi that prints \"Hi\". Read a number -- if it's greater than 1, call hi() twice, otherwise once.",
     ["functions"],
     [{"input": ["2"], "expected": "Hi\nHi"}, {"input": ["1"], "expected": "Hi"}, {"input": ["5"], "expected": "Hi\nHi"}]),
    ("Triple It (Parameter)", 3, "fundamentals",
     "Write a function called triple that takes one parameter and returns it times 3. Read a number, call triple(), and print the result.",
     ["parameters"],
     [{"input": ["3"], "expected": "9"}, {"input": ["10"], "expected": "30"}]),
    ("Greet By Name (Parameter)", 3, "fundamentals",
     "Write a function called greet that takes a name and prints \"Hi, \" followed by it. Read a name and call greet() with it.",
     ["parameters"],
     [{"input": ["Sam"], "expected": "Hi, Sam"}]),
    ("Max of Two", 3, "fundamentals",
     "Write a function called bigger that takes two parameters and returns whichever is larger. Read two numbers, call it, and print the result.",
     ["parameters"],
     [{"input": ["5", "3"], "expected": "5"}, {"input": ["2", "8"], "expected": "8"}]),
    ("Repeat With a Parameter", 3, "fundamentals",
     "Write a function called say_hi that takes a number and prints \"Hi\" that many times using a loop. Read a number and call it.",
     ["parameters"],
     [{"input": ["3"], "expected": "Hi\nHi\nHi"}, {"input": ["1"], "expected": "Hi"}]),
    ("Multiply Two Params", 3, "fundamentals",
     "Write a function called multiply that takes two parameters and returns their product. Read two numbers, call it, and print the result.",
     ["parameters"],
     [{"input": ["4", "5"], "expected": "20"}, {"input": ["3", "3"], "expected": "9"}]),
    ("Is Even Parameter", 3, "fundamentals",
     "Write a function called is_even that takes a number and returns whether it's even. Read a number, call it, and print the result.",
     ["parameters"],
     [{"input": ["4"], "expected": "True"}, {"input": ["7"], "expected": "False"}]),
    ("Three Parameters", 3, "fundamentals",
     "Write a function called add_three that takes three parameters and returns their sum. Read three numbers, call it, and print the result.",
     ["parameters"],
     [{"input": ["1", "2", "3"], "expected": "6"}, {"input": ["10", "10", "10"], "expected": "30"}]),
    ("Shout Twice", 3, "fundamentals",
     "Write a function called shout that takes a word and prints it followed by \"!!!\". Read a word and call shout() with it twice.",
     ["parameters"],
     [{"input": ["go"], "expected": "go!!!\ngo!!!"}]),
    ("Subtract Params", 3, "fundamentals",
     "Write a function called subtract that takes two parameters and returns the first minus the second. Read two numbers, call it, and print the result.",
     ["parameters"],
     [{"input": ["10", "4"], "expected": "6"}, {"input": ["3", "9"], "expected": "-6"}]),
    ("Parameter Used in a Loop Range", 3, "fundamentals",
     "Write a function called count_up that takes a number and prints 1 through it, one per line, using the parameter inside a loop.",
     ["parameters"],
     [{"input": ["3"], "expected": "1\n2\n3"}, {"input": ["5"], "expected": "1\n2\n3\n4\n5"}]),
    ("Area of a Rectangle", 3, "fundamentals",
     "Read a width and a height and print their product (the area).",
     ["simple_math"],
     [{"input": ["4", "5"], "expected": "20"}, {"input": ["3", "3"], "expected": "9"}]),
    ("Subtract in Order", 3, "fundamentals",
     "Read two numbers and print the first one minus the second one.",
     ["simple_math"],
     [{"input": ["10", "3"], "expected": "7"}, {"input": ["2", "9"], "expected": "-7"}]),
    ("Square a Number", 3, "fundamentals",
     "Read a number and print it multiplied by itself.",
     ["simple_math"],
     [{"input": ["5"], "expected": "25"}, {"input": ["7"], "expected": "49"}]),
    ("Half of It", 3, "fundamentals",
     "Read a whole number and print it divided by 2 using integer division (//).",
     ["simple_math"],
     [{"input": ["10"], "expected": "5"}, {"input": ["7"], "expected": "3"}]),
    ("Is It Divisible", 3, "fundamentals",
     "Read two numbers and print \"yes\" if the first is evenly divisible by the second, otherwise \"no\".",
     ["simple_math"],
     [{"input": ["10", "5"], "expected": "yes"}, {"input": ["7", "2"], "expected": "no"}]),
    ("Sum of Three", 3, "fundamentals",
     "Read three numbers and print their sum.",
     ["simple_math"],
     [{"input": ["1", "2", "3"], "expected": "6"}, {"input": ["10", "20", "30"], "expected": "60"}]),
    ("Convert Celsius to Fahrenheit", 3, "fundamentals",
     "Read a Celsius temperature and print it converted to Fahrenheit using f = c * 9 / 5 + 32.",
     ["simple_math"],
     [{"input": ["0"], "expected": "32.0"}, {"input": ["100"], "expected": "212.0"}]),
    ("Exponent Practice", 3, "fundamentals",
     "Read a base and an exponent and print the base raised to that power using **.",
     ["simple_math"],
     [{"input": ["2", "3"], "expected": "8"}, {"input": ["3", "2"], "expected": "9"}]),
    ("Absolute Difference", 3, "fundamentals",
     "Read two numbers and print the absolute value of their difference using abs().",
     ["simple_math"],
     [{"input": ["3", "10"], "expected": "7"}, {"input": ["10", "3"], "expected": "7"}]),
    ("Perimeter of a Square", 3, "fundamentals",
     "Read a side length and print the perimeter of a square with that side (4 times the side).",
     ["simple_math"],
     [{"input": ["5"], "expected": "20"}, {"input": ["3"], "expected": "12"}]),
    ("Seeded Coin Flip", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.choice() between \"heads\" and \"tails\".",
     ["random_library"],
     [{"input": ["1"], "expected": "heads"}, {"input": ["3"], "expected": "tails"}, {"input": ["6"], "expected": "tails"}]),
    ("Seeded Dice Roll", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.randint(1, 6).",
     ["random_library"],
     [{"input": ["4"], "expected": "6"}, {"input": ["12"], "expected": "1"}, {"input": ["77"], "expected": "6"}]),
    ("Seeded Pick from Numbers", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.choice() on the list [10, 20, 30, 40].",
     ["random_library"],
     [{"input": ["6"], "expected": "40"}, {"input": ["19"], "expected": "10"}, {"input": ["31"], "expected": "20"}]),
    ("Seeded Random Between", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.randint(1, 100).",
     ["random_library"],
     [{"input": ["14"], "expected": "52"}, {"input": ["21"], "expected": "5"}, {"input": ["50"], "expected": "50"}]),
    ("Seeded Random Float", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.random().",
     ["random_library"],
     [{"input": ["1"], "expected": "0.417022004702574"}, {"input": ["2"], "expected": "0.4359949021420038"}]),
    ("Seeded Pick a Letter", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.choice() on a list of 5 letters.",
     ["random_library"],
     [{"input": ["7"], "expected": "a"}, {"input": ["13"], "expected": "d"}, {"input": ["25"], "expected": "e"}]),
    ("Seeded Random in Range", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.randint(1, 3).",
     ["random_library"],
     [{"input": ["4"], "expected": "3"}, {"input": ["15"], "expected": "3"}, {"input": ["26"], "expected": "1"}]),
    ("Seeded Pick a Day", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.choice() on a list of weekday names.",
     ["random_library"],
     [{"input": ["9"], "expected": "Mon"}, {"input": ["17"], "expected": "Tue"}, {"input": ["29"], "expected": "Fri"}]),
    ("Seeded Dice Twice", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Call random.randint(1, 6) twice and print both results, one per line.",
     ["random_library"],
     [{"input": ["3"], "expected": "4\n5"}, {"input": ["16"], "expected": "2\n4"}]),
    ("Seeded Number Then Choice", 3, "fundamentals",
     "Import random. Read a whole number and use it as a seed with random.seed(). Print the result of random.randint(1, 10), then the result of random.choice() on a list of 3 colors.",
     ["random_library"],
     [{"input": ["5"], "expected": "3\nblue"}, {"input": ["18"], "expected": "7\ngreen"}]),
    ("Sign of a Number", 3, "fundamentals",
     "Read a number and print \"positive\", \"negative\", or \"zero\" using if/elif/else.",
     ["conditionals"],
     [{"input": ["5"], "expected": "positive"}, {"input": ["-3"], "expected": "negative"}, {"input": ["0"], "expected": "zero"}]),
    ("Grade From Score", 3, "fundamentals",
     "Read a test score and print a letter grade: A for 90+, B for 80+, C for 70+, otherwise F. Use if/elif/else.",
     ["conditionals"],
     [{"input": ["95"], "expected": "A"}, {"input": ["85"], "expected": "B"}, {"input": ["72"], "expected": "C"}, {"input": ["50"], "expected": "F"}]),
    ("Biggest of Three (If/Elif)", 3, "fundamentals",
     "Read 3 numbers and print the largest one using if/elif/else (no max(), no list) -- compare them directly.",
     ["conditionals"],
     [{"input": ["3", "9", "5"], "expected": "9"}, {"input": ["10", "2", "7"], "expected": "10"}, {"input": ["1", "2", "9"], "expected": "9"}]),
    ("Weekday or Weekend", 3, "fundamentals",
     "Read a day name and print \"weekend\" if it's Saturday or Sunday, otherwise \"weekday\".",
     ["conditionals"],
     [{"input": ["Saturday"], "expected": "weekend"}, {"input": ["Monday"], "expected": "weekday"}, {"input": ["Sunday"], "expected": "weekend"}]),
    ("Temperature Advice", 3, "fundamentals",
     "Read a temperature and print \"It is hot\" (85+), \"It is nice\" (60+), or \"It is cold\", using if/elif/else.",
     ["conditionals"],
     [{"input": ["90"], "expected": "It is hot"}, {"input": ["70"], "expected": "It is nice"}, {"input": ["40"], "expected": "It is cold"}]),
    ("Even, Odd, or Zero", 3, "fundamentals",
     "Read a number and print \"zero\", \"even\", or \"odd\" -- check for zero before checking even/odd.",
     ["conditionals"],
     [{"input": ["0"], "expected": "zero"}, {"input": ["4"], "expected": "even"}, {"input": ["7"], "expected": "odd"}]),
    ("Ticket Price by Age", 3, "fundamentals",
     "Read an age and print the ticket price: 0 under 5, 10 under 18, otherwise 15. Use if/elif/else.",
     ["conditionals"],
     [{"input": ["3"], "expected": "0"}, {"input": ["12"], "expected": "10"}, {"input": ["30"], "expected": "15"}]),
    ("Two Conditions With And", 3, "fundamentals",
     "Read a number and print \"positive even\" if it's both greater than 0 AND even, otherwise \"not positive even\".",
     ["conditionals"],
     [{"input": ["4"], "expected": "positive even"}, {"input": ["-4"], "expected": "not positive even"}, {"input": ["3"], "expected": "not positive even"}]),
    ("Login Check", 3, "fundamentals",
     "Read a username and a PIN. Print \"access granted\" only if the username is \"admin\" AND the PIN is \"1234\", otherwise \"access denied\".",
     ["conditionals"],
     [{"input": ["admin", "1234"], "expected": "access granted"}, {"input": ["admin", "0000"], "expected": "access denied"}, {"input": ["guest", "1234"], "expected": "access denied"}]),
    ("Rock Paper Scissors Winner", 3, "fundamentals",
     "Read two moves (rock/paper/scissors) and print who wins: \"tie\", \"player 1 wins\", or \"player 2 wins\", using if/elif/else.",
     ["conditionals"],
     [{"input": ["rock", "scissors"], "expected": "player 1 wins"}, {"input": ["paper", "rock"], "expected": "player 1 wins"}, {"input": ["rock", "paper"], "expected": "player 2 wins"}, {"input": ["rock", "rock"], "expected": "tie"}]),
    ("Stop At First Match", 3, "fundamentals",
     "Loop from 1 upward and use break to stop and print the number the moment it equals the one read from input().",
     ["loops_breaks"],
     [{"input": ["7"], "expected": "7"}, {"input": ["42"], "expected": "42"}]),
    ("Find First Multiple", 3, "fundamentals",
     "Read a number n, loop upward from 1, and use break to stop at and print the very first multiple of n.",
     ["loops_breaks"],
     [{"input": ["7"], "expected": "7"}, {"input": ["13"], "expected": "13"}]),
    ("Search a List and Stop", 3, "fundamentals",
     "Given a fixed list of numbers, read a target and loop through the list, using break the moment you find it, then print whether it was found.",
     ["loops_breaks"],
     [{"input": ["15"], "expected": "True"}, {"input": ["100"], "expected": "False"}]),
    ("Skip the Multiples of Three", 3, "fundamentals",
     "Read a whole number n and print every number from 1 to n EXCEPT multiples of 3, using continue to skip them.",
     ["loops_breaks"],
     [{"input": ["6"], "expected": "1\n2\n4\n5"}, {"input": ["9"], "expected": "1\n2\n4\n5\n7\n8"}]),
    ("Sum Until Negative", 3, "fundamentals",
     "Read up to n numbers one at a time, adding each to a running total, but stop early with break the moment a negative number appears. Print the total.",
     ["loops_breaks"],
     [{"input": ["5", "3", "4", "-1", "10", "10"], "expected": "7"}, {"input": ["3", "1", "2", "3"], "expected": "6"}]),
    ("Print Until a Word", 3, "fundamentals",
     "Read up to n words one at a time and print each one, but stop early with break the moment the word \"stop\" appears.",
     ["loops_breaks"],
     [{"input": ["4", "cat", "dog", "stop", "fish"], "expected": "cat\ndog"}, {"input": ["2", "hi", "bye"], "expected": "hi\nbye"}]),
    ("Only Print Positives", 3, "fundamentals",
     "Read n numbers one at a time and print only the positive ones, using continue to skip zero or negative numbers.",
     ["loops_breaks"],
     [{"input": ["4", "3", "-1", "0", "5"], "expected": "3\n5"}, {"input": ["3", "1", "2", "3"], "expected": "1\n2\n3"}]),
    ("First Even Number", 3, "fundamentals",
     "Read numbers one at a time and use break to stop at and print the very first even number.",
     ["loops_breaks"],
     [{"input": ["4", "3", "7", "8", "1"], "expected": "8"}, {"input": ["3", "2", "4", "6"], "expected": "2"}]),
    ("Countdown With an Early Stop", 3, "fundamentals",
     "Count down from n, but use break to stop before printing a specific number read from input().",
     ["loops_breaks"],
     [{"input": ["5", "2"], "expected": "5\n4\n3"}, {"input": ["10", "8"], "expected": "10\n9"}]),
    ("While Loop With Break", 3, "fundamentals",
     "Use a while True loop with an if/break inside it to count up from 1 to n, one per line, instead of a for loop.",
     ["loops_breaks"],
     [{"input": ["3"], "expected": "1\n2\n3"}, {"input": ["5"], "expected": "1\n2\n3\n4\n5"}]),
]

# Hand-picked, kid-appropriate vocabulary for generated login handles
# (e.g. "PinkPanther29") -- deliberately not an external name-generator
# package, so every possible word is one we've actually looked at.
HANDLE_ADJECTIVES = [
    "Pink", "Blue", "Green", "Golden", "Silver", "Speedy", "Jumpy", "Silly",
    "Clever", "Brave", "Mighty", "Sneaky", "Bouncy", "Fuzzy", "Sparkly",
    "Cosmic", "Turbo", "Zippy", "Happy", "Lucky",
]
HANDLE_ANIMALS = [
    "Panther", "Tiger", "Falcon", "Otter", "Dolphin", "Fox", "Wolf", "Panda",
    "Koala", "Hedgehog", "Raccoon", "Penguin", "Narwhal", "Gecko", "Lynx",
    "Badger", "Heron", "Marmot", "Cobra", "Puffin",
]


def get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._db = dbmod.connect()
    return db


@app.teardown_appcontext
def close_db(_exc):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def _ensure_column(db, table, column, coldef):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")


def init_db():
    db = dbmod.connect()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS families (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            claim_code TEXT
        );
        CREATE TABLE IF NOT EXISTS parents (
            id TEXT PRIMARY KEY,
            family_id TEXT NOT NULL,
            google_sub TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            display_name TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_parents_family_id ON parents(family_id);
        CREATE TABLE IF NOT EXISTS kids (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            brief TEXT NOT NULL,
            points INTEGER NOT NULL,
            difficulty TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            title TEXT NOT NULL,
            points INTEGER NOT NULL,
            explanation TEXT,
            code TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            review_note TEXT,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS redemptions (
            id TEXT PRIMARY KEY,
            minutes INTEGER NOT NULL,
            points INTEGER NOT NULL,
            date TEXT NOT NULL,
            redeemed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            family_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (family_id, key)
        );
        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            goal_points INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_code ON teams(code);
        """
    )
    for table in ("tasks", "submissions", "redemptions"):
        _ensure_column(db, table, "kid_id", "kid_id TEXT NOT NULL DEFAULT 'shayne'")
    _ensure_column(db, "tasks", "source", "source TEXT NOT NULL DEFAULT 'seed'")
    _ensure_column(db, "tasks", "status", "status TEXT NOT NULL DEFAULT 'active'")
    _ensure_column(db, "tasks", "skills", "skills TEXT")
    # Added mid-project (this session) but never covered by an
    # _ensure_column call -- a genuinely fresh install would have crashed
    # on GET /api/tasks (row_to_task reads both unconditionally).
    _ensure_column(db, "tasks", "vehicle", "vehicle TEXT NOT NULL DEFAULT 'turtle'")
    _ensure_column(db, "tasks", "test_cases", "test_cases TEXT")
    _ensure_column(db, "submissions", "snapshot", "snapshot TEXT")
    _ensure_column(db, "submissions", "pasted", "pasted INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "kids", "pin", "pin TEXT NOT NULL DEFAULT '0000'")
    _ensure_column(db, "kids", "avatar", "avatar TEXT")
    # Multi-family additions -- nullable/defaulted so this is safe to run
    # against a DB that hasn't been through migrate_multitenant.py yet
    # (local fresh installs; the one production DB gets migrated
    # separately, once, by that script rather than by booting new code
    # against it un-migrated).
    _ensure_column(db, "kids", "family_id", "family_id TEXT")
    _ensure_column(db, "kids", "handle", "handle TEXT")
    _ensure_column(db, "kids", "failed_pin_count", "failed_pin_count INTEGER NOT NULL DEFAULT 0")
    _ensure_column(db, "kids", "pin_locked_until", "pin_locked_until TEXT")
    # Cross-family teams -- deliberately the one place a kid's data is
    # visible outside their own family (see /api/teams/me). Nullable: a
    # kid is on at most one team at a time, enforced just by this being
    # a single column rather than a join table.
    _ensure_column(db, "kids", "team_id", "team_id TEXT")
    # Must run after the _ensure_column call above -- kids predates
    # family_id (an existing table gaining a new column), unlike parents,
    # which is created fresh with family_id already in its column list.
    db.execute("CREATE INDEX IF NOT EXISTS idx_kids_family_id ON kids(family_id)")
    dbmod.commit_and_sync(db)
    db.close()


row_to_task = dbmod.row_to_task
row_to_submission = dbmod.row_to_submission
row_to_redemption = dbmod.row_to_redemption
row_to_kid = dbmod.row_to_kid


# ---------------- Auth helpers ----------------

def require_family_session(fn):
    """Any logged-in identity (kid or parent) within a family. Populates
    g.family_id (always), g.kid_id / g.parent_id (whichever role is
    active, the other is None) -- route bodies use these, never a
    client-supplied value, to decide what's visible/touchable."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        family_id = session.get("family_id")
        if not family_id:
            return jsonify({"error": "not logged in"}), 401
        g.family_id = family_id
        g.kid_id = session.get("kid_id")
        g.parent_id = session.get("parent_id")
        return fn(*args, **kwargs)
    return wrapper


def require_parent_login(fn):
    """Parent-only actions (task/submission/kid/settings management)."""
    @wraps(fn)
    @require_family_session
    def wrapper(*args, **kwargs):
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _kid_family_id(db, kid_id):
    row = dbmod.fetchone(db.execute("SELECT family_id FROM kids WHERE id=?", (kid_id,)))
    return row["family_id"] if row else None


def _task_family_id(db, task_id):
    row = dbmod.fetchone(db.execute(
        "SELECT kids.family_id AS family_id FROM tasks JOIN kids ON kids.id = tasks.kid_id WHERE tasks.id=?",
        (task_id,),
    ))
    return row["family_id"] if row else None


def _submission_family_id(db, sub_id):
    row = dbmod.fetchone(db.execute(
        "SELECT kids.family_id AS family_id FROM submissions JOIN kids ON kids.id = submissions.kid_id WHERE submissions.id=?",
        (sub_id,),
    ))
    return row["family_id"] if row else None


def generate_kid_handle(db):
    for _ in range(20):
        handle = (random.choice(HANDLE_ADJECTIVES) + random.choice(HANDLE_ANIMALS)
                  + str(random.randint(10, 99)))
        exists = dbmod.fetchone(db.execute(
            "SELECT 1 FROM kids WHERE lower(handle) = lower(?)", (handle,)
        ))
        if not exists:
            return handle
    # Word-list x 2-digit-number space is ~8000-large; 20 collisions in a
    # row would mean something's actually wrong, not just bad luck.
    raise RuntimeError("could not generate a unique kid handle")


# Excludes visually-ambiguous characters (0/O, 1/I/L) -- kids read this
# code off a screen or a piece of paper to share with a friend, so it
# needs to survive that without transcription errors.
TEAM_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_team_code(db):
    for _ in range(20):
        code = "".join(random.choice(TEAM_CODE_ALPHABET) for _ in range(6))
        exists = dbmod.fetchone(db.execute("SELECT 1 FROM teams WHERE code=?", (code,)))
        if not exists:
            return code
    raise RuntimeError("could not generate a unique team code")


# Fundamentals Practice draws from a bank of 100 questions (see
# STARTER_FUNDAMENTALS_TASKS) but only ever shows this many at once --
# the rest sit in status='reserve' and get activated one at a time as
# the kid completes an active one (see create_submission).
FUNDAMENTALS_ACTIVE_COUNT = 10


def seed_starter_tasks_for_kid(db, kid_id):
    rows = []
    for title, points, diff, brief, skills in STARTER_TURTLE_TASKS:
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), "active", "turtle", None))
    for title, points, diff, brief, skills, test_cases in STARTER_JUDGE_TASKS:
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), "active", "judge", json.dumps(test_cases)))
    shuffled_fundamentals = list(STARTER_FUNDAMENTALS_TASKS)
    random.shuffle(shuffled_fundamentals)
    for i, (title, points, diff, brief, skills, test_cases) in enumerate(shuffled_fundamentals):
        status = "active" if i < FUNDAMENTALS_ACTIVE_COUNT else "reserve"
        rows.append(("t_" + uuid.uuid4().hex[:10], title, points, diff, brief, kid_id,
                      json.dumps(skills), status, "judge", json.dumps(test_cases)))
    db.executemany(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status, vehicle, test_cases)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'seed', ?, ?, ?)""",
        rows,
    )


def activate_one_reserve_fundamentals_task(db, kid_id):
    """Tops the kid's visible Fundamentals Practice pool back up to
    FUNDAMENTALS_ACTIVE_COUNT by promoting one random reserve task to
    active -- called whenever a fundamentals task is submitted (see
    create_submission), so completing one always frees up a slot that
    immediately gets refilled from the 100-question bank."""
    reserve = dbmod.fetchall(db.execute(
        "SELECT id FROM tasks WHERE kid_id=? AND difficulty='fundamentals' AND status='reserve'",
        (kid_id,),
    ))
    if not reserve:
        return
    chosen = random.choice(reserve)
    db.execute("UPDATE tasks SET status='active' WHERE id=?", (chosen["id"],))


def create_default_settings(db, family_id):
    for key, value in DEFAULT_SETTINGS.items():
        db.execute(
            "INSERT OR IGNORE INTO settings (family_id, key, value) VALUES (?, ?, ?)",
            (family_id, key, value),
        )


# ---------------- Frontend ----------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------- Kids ----------------

@app.route("/api/kids", methods=["GET"])
@require_parent_login
def list_kids():
    db = get_db()
    rows = dbmod.fetchall(db.execute(
        """SELECT kids.*, teams.name AS team_name FROM kids
           LEFT JOIN teams ON teams.id = kids.team_id
           WHERE kids.family_id=?""",
        (g.family_id,),
    ))
    out = []
    for r in rows:
        kid = row_to_kid(r)
        kid["teamName"] = r["team_name"]
        out.append(kid)
    return jsonify(out)


@app.route("/api/kids", methods=["POST"])
@require_parent_login
def create_kid():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "missing field: name"}), 400
    db = get_db()
    kid_id = "kid_" + uuid.uuid4().hex[:10]
    handle = generate_kid_handle(db)
    db.execute(
        "INSERT INTO kids (id, name, family_id, handle, pin) VALUES (?, ?, ?, ?, '0000')",
        (kid_id, name, g.family_id, handle),
    )
    seed_starter_tasks_for_kid(db, kid_id)
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (kid_id,)))
    return jsonify(row_to_kid(row)), 201


@app.route("/api/kids/<kid_id>", methods=["PUT"])
@require_parent_login
def update_kid(kid_id):
    db = get_db()
    if _kid_family_id(db, kid_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    # Whitelisted columns, never taken from the request key itself, so
    # interpolating the column name here is safe -- only the value is a
    # bind parameter.
    for key in ("pin", "avatar", "name", "handle"):
        if key in data:
            db.execute(f"UPDATE kids SET {key}=? WHERE id=?", (data[key], kid_id))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (kid_id,)))
    return jsonify(row_to_kid(row))


# ---------------- Tasks ----------------

@app.route("/api/tasks", methods=["GET"])
@require_family_session
def list_tasks():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='active'", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT tasks.* FROM tasks JOIN kids ON kids.id = tasks.kid_id "
            "WHERE kids.family_id=? AND tasks.status='active'", (g.family_id,)
        ))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["GET"])
@require_family_session
def list_suggestions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM tasks WHERE kid_id=? AND status='queued'", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT tasks.* FROM tasks JOIN kids ON kids.id = tasks.kid_id "
            "WHERE kids.family_id=? AND tasks.status='queued'", (g.family_id,)
        ))
    return jsonify([row_to_task(r) for r in rows])


@app.route("/api/tasks/suggestions", methods=["POST"])
def create_suggestion():
    # Deliberately unauthenticated, unlike POST /api/tasks: a suggestion is
    # inert until a parent explicitly approves it in Parent > Suggestions,
    # so the approval step is the real security boundary here, not this
    # endpoint. This is what lets a scheduled agent (no DB credentials, no
    # session) propose new tasks over plain HTTPS. kidId must still name a
    # real, existing kid -- there's no family session to scope by here, so
    # existence is the only check available (matches curate_tasks.py's
    # actual usage, which writes directly to the DB and already knows a
    # real kid_id; this endpoint is a separate, currently-unused-by-anything
    # HTTP integration surface, hardened the same way regardless).
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    db = get_db()
    if not dbmod.fetchone(db.execute("SELECT 1 FROM kids WHERE id=?", (data["kidId"],))):
        return jsonify({"error": "unknown kidId"}), 400
    task_id = "a_" + uuid.uuid4().hex[:10]
    db.execute(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, skills, source, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'agent', 'queued')""",
        (task_id, data["title"], int(data["points"]), data["difficulty"], data["brief"], data["kidId"],
         json.dumps(data.get("skills", []))),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/suggestions/<task_id>/approve", methods=["POST"])
@require_parent_login
def approve_suggestion(task_id):
    db = get_db()
    if _task_family_id(db, task_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    db.execute("UPDATE tasks SET status='active' WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row))


@app.route("/api/tasks", methods=["POST"])
@require_parent_login
def create_task():
    data = request.get_json(force=True)
    for field in ("title", "brief", "points", "difficulty", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    db = get_db()
    if _kid_family_id(db, data["kidId"]) != g.family_id:
        return jsonify({"error": "unknown kidId"}), 400
    task_id = "t_" + uuid.uuid4().hex[:10]
    db.execute(
        """INSERT INTO tasks (id, title, points, difficulty, brief, kid_id, source, status)
           VALUES (?, ?, ?, ?, ?, ?, 'parent', 'active')""",
        (task_id, data["title"], int(data["points"]), data["difficulty"], data["brief"], data["kidId"]),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)))
    return jsonify(row_to_task(row)), 201


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@require_parent_login
def delete_task(task_id):
    db = get_db()
    if _task_family_id(db, task_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    dbmod.commit_and_sync(db)
    return jsonify({"deleted": task_id})


# ---------------- Submissions ----------------

@app.route("/api/submissions", methods=["GET"])
@require_family_session
def list_submissions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM submissions WHERE kid_id=? ORDER BY submitted_at ASC", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT submissions.* FROM submissions JOIN kids ON kids.id = submissions.kid_id "
            "WHERE kids.family_id=? ORDER BY submitted_at ASC", (g.family_id,)
        ))
    return jsonify([row_to_submission(r) for r in rows])


@app.route("/api/submissions", methods=["POST"])
@require_family_session
def create_submission():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    for field in ("taskId", "title", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    if data["kidId"] != g.kid_id:
        return jsonify({"error": "forbidden"}), 403
    sub_id = "sub_" + uuid.uuid4().hex[:10]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute(
        """INSERT INTO submissions (id, task_id, title, points, explanation, code, status, submitted_at, kid_id, snapshot, pasted)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
        (sub_id, data["taskId"], data["title"], int(data["points"]),
         data.get("explanation", ""), data.get("code", ""), now, data["kidId"], data.get("snapshot"),
         1 if data.get("pasted") else 0),
    )
    task = dbmod.fetchone(db.execute("SELECT difficulty FROM tasks WHERE id=?", (data["taskId"],)))
    if task and task["difficulty"] == "fundamentals":
        activate_one_reserve_fundamentals_task(db, g.kid_id)
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    return jsonify(row_to_submission(row)), 201


@app.route("/api/submissions/<sub_id>", methods=["PATCH"])
@require_parent_login
def review_submission(sub_id):
    db = get_db()
    if _submission_family_id(db, sub_id) != g.family_id:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(force=True)
    status = data.get("status")
    if status not in ("approved", "rejected"):
        return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    db.execute(
        "UPDATE submissions SET status=?, review_note=?, reviewed_at=? WHERE id=?",
        (status, data.get("reviewNote", ""), now, sub_id),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)))
    return jsonify(row_to_submission(row))


# ---------------- Redemptions ----------------

@app.route("/api/redemptions", methods=["GET"])
@require_family_session
def list_redemptions():
    db = get_db()
    kid = request.args.get("kid")
    if kid:
        if g.kid_id and kid != g.kid_id:
            return jsonify({"error": "forbidden"}), 403
        if _kid_family_id(db, kid) != g.family_id:
            return jsonify({"error": "forbidden"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT * FROM redemptions WHERE kid_id=? ORDER BY redeemed_at ASC", (kid,)
        ))
    else:
        if not g.parent_id:
            return jsonify({"error": "parent login required"}), 403
        rows = dbmod.fetchall(db.execute(
            "SELECT redemptions.* FROM redemptions JOIN kids ON kids.id = redemptions.kid_id "
            "WHERE kids.family_id=? ORDER BY redeemed_at ASC", (g.family_id,)
        ))
    return jsonify([row_to_redemption(r) for r in rows])


@app.route("/api/redemptions", methods=["POST"])
@require_family_session
def create_redemption():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    for field in ("minutes", "points", "kidId"):
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400
    if data["kidId"] != g.kid_id:
        return jsonify({"error": "forbidden"}), 403
    red_id = "red_" + uuid.uuid4().hex[:10]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    today = date.today().isoformat()
    db = get_db()
    db.execute(
        "INSERT INTO redemptions (id, minutes, points, date, redeemed_at, kid_id) VALUES (?, ?, ?, ?, ?, ?)",
        (red_id, int(data["minutes"]), int(data["points"]), today, now_iso, data["kidId"]),
    )
    dbmod.commit_and_sync(db)
    row = dbmod.fetchone(db.execute("SELECT * FROM redemptions WHERE id=?", (red_id,)))
    return jsonify(row_to_redemption(row)), 201


# ---------------- Auth ----------------

PIN_LOCKOUT_THRESHOLD = 5
PIN_LOCKOUT_MINUTES = 5


@app.route("/api/auth/kid-login", methods=["POST"])
def kid_login():
    data = request.get_json(force=True)
    handle = (data.get("handle") or "").strip()
    pin = data.get("pin", "")
    db = get_db()
    row = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE lower(handle) = lower(?)", (handle,)))
    if not row:
        return jsonify({"ok": False, "error": "unknown handle"}), 401
    now = datetime.utcnow()
    if row["pin_locked_until"]:
        locked_until = datetime.fromisoformat(row["pin_locked_until"])
        if now < locked_until:
            return jsonify({"ok": False, "error": "locked", "lockedUntil": row["pin_locked_until"]}), 429
    if pin != row["pin"]:
        failed = (row["failed_pin_count"] or 0) + 1
        locked_until = None
        if failed >= PIN_LOCKOUT_THRESHOLD:
            locked_until = (now + timedelta(minutes=PIN_LOCKOUT_MINUTES)).isoformat()
            failed = 0
        db.execute(
            "UPDATE kids SET failed_pin_count=?, pin_locked_until=? WHERE id=?",
            (failed, locked_until, row["id"]),
        )
        dbmod.commit_and_sync(db)
        return jsonify({"ok": False, "error": "wrong pin"}), 401
    db.execute("UPDATE kids SET failed_pin_count=0, pin_locked_until=NULL WHERE id=?", (row["id"],))
    dbmod.commit_and_sync(db)
    session.clear()
    session["kid_id"] = row["id"]
    session["family_id"] = row["family_id"]
    session.permanent = True
    return jsonify({"ok": True, "kid": row_to_kid(row)})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
def auth_me():
    family_id = session.get("family_id")
    if not family_id:
        return jsonify({"role": None})
    db = get_db()
    family = dbmod.fetchone(db.execute("SELECT * FROM families WHERE id=?", (family_id,)))
    if session.get("kid_id"):
        kid = dbmod.fetchone(db.execute("SELECT * FROM kids WHERE id=?", (session["kid_id"],)))
        if not kid:
            session.clear()
            return jsonify({"role": None})
        return jsonify({"role": "kid", "kid": row_to_kid(kid), "familyName": family["name"] if family else None})
    if session.get("parent_id"):
        parent = dbmod.fetchone(db.execute("SELECT * FROM parents WHERE id=?", (session["parent_id"],)))
        if not parent:
            session.clear()
            return jsonify({"role": None})
        return jsonify({
            "role": "parent",
            "email": parent["email"],
            "familyName": family["name"] if family else None,
        })
    session.clear()
    return jsonify({"role": None})


@app.route("/api/auth/google/login", methods=["GET"])
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/api/auth/google/callback", methods=["GET"])
def google_callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo")
    if not userinfo:
        # Older/edge-case Authlib response shapes don't always attach
        # userinfo to the token dict automatically -- fall back to
        # parsing the id_token explicitly rather than assuming.
        userinfo = oauth.google.parse_id_token(token)
    google_sub = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name") or email.split("@")[0]

    db = get_db()
    parent = dbmod.fetchone(db.execute("SELECT * FROM parents WHERE google_sub=?", (google_sub,)))
    now = datetime.utcnow().isoformat()

    if parent is None:
        claim_code = session.pop("pending_claim_code", None)
        family = None
        if claim_code:
            family = dbmod.fetchone(db.execute(
                "SELECT * FROM families WHERE claim_code=?", (claim_code,)
            ))
        if family:
            family_id = family["id"]
            db.execute("UPDATE families SET claim_code=NULL WHERE id=?", (family_id,))
        else:
            family_id = "fam_" + uuid.uuid4().hex[:10]
            db.execute(
                "INSERT INTO families (id, name, created_at) VALUES (?, ?, ?)",
                (family_id, f"{name}'s Family", now),
            )
            create_default_settings(db, family_id)
        parent_id = "par_" + uuid.uuid4().hex[:10]
        db.execute(
            "INSERT INTO parents (id, family_id, google_sub, email, display_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (parent_id, family_id, google_sub, email, name, now),
        )
        dbmod.commit_and_sync(db)
        session.clear()
        session["parent_id"] = parent_id
        session["family_id"] = family_id
    else:
        dbmod.commit_and_sync(db)
        session.clear()
        session["parent_id"] = parent["id"]
        session["family_id"] = parent["family_id"]
    session.permanent = True
    return redirect("/")


@app.route("/api/auth/claim/<code>", methods=["GET"])
def claim_family(code):
    # One-time handoff used only by the production migration: visiting
    # this link stashes the claim code, then sends the real owner through
    # the normal Google login flow, which attaches their new parents row
    # to the pre-migrated family instead of creating an empty new one.
    db = get_db()
    family = dbmod.fetchone(db.execute("SELECT * FROM families WHERE claim_code=?", (code,)))
    if not family:
        return "This claim link is invalid or has already been used.", 404
    session["pending_claim_code"] = code
    return redirect(url_for("google_login"))


# ---------------- Settings ----------------

@app.route("/api/settings", methods=["GET"])
@require_family_session
def get_settings():
    db = get_db()
    rows = dbmod.fetchall(db.execute("SELECT key, value FROM settings WHERE family_id=?", (g.family_id,)))
    out = {r["key"]: r["value"] for r in rows}
    return jsonify({
        "pointsPerMinute": float(out.get("pointsPerMinute", 1)),
        "dailyCapMinutes": int(out.get("dailyCapMinutes", 60)),
    })


@app.route("/api/settings", methods=["PUT"])
@require_parent_login
def update_settings():
    data = request.get_json(force=True)
    db = get_db()
    for key in ("pointsPerMinute", "dailyCapMinutes"):
        if key in data:
            db.execute(
                "INSERT INTO settings (family_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT(family_id, key) DO UPDATE SET value=excluded.value",
                (g.family_id, key, str(data[key])),
            )
    dbmod.commit_and_sync(db)
    return get_settings()


# ---------------- Teams ----------------
# Kid-facing only -- parents don't manage teams directly. A team crosses
# family boundaries on purpose (the one place in this codebase that's
# true), so every route here must stay narrow about what it exposes:
# handle + points, never name/email/family_id/pin.

@app.route("/api/teams", methods=["POST"])
@require_family_session
def create_team():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "missing field: name"}), 400
    try:
        goal_points = int(data.get("goalPoints") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "goalPoints must be a number"}), 400
    db = get_db()
    team_id = "team_" + uuid.uuid4().hex[:10]
    code = generate_team_code(db)
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO teams (id, name, code, goal_points, created_at) VALUES (?, ?, ?, ?, ?)",
        (team_id, name, code, goal_points, now),
    )
    db.execute("UPDATE kids SET team_id=? WHERE id=?", (team_id, g.kid_id))
    dbmod.commit_and_sync(db)
    return jsonify({"id": team_id, "name": name, "code": code, "goalPoints": goal_points}), 201


@app.route("/api/teams/join", methods=["POST"])
@require_family_session
def join_team():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip().upper()
    db = get_db()
    team = dbmod.fetchone(db.execute("SELECT * FROM teams WHERE code=?", (code,)))
    if not team:
        return jsonify({"error": "unknown team code"}), 404
    db.execute("UPDATE kids SET team_id=? WHERE id=?", (team["id"], g.kid_id))
    dbmod.commit_and_sync(db)
    return jsonify({"id": team["id"], "name": team["name"], "code": team["code"], "goalPoints": team["goal_points"]})


@app.route("/api/teams/leave", methods=["POST"])
@require_family_session
def leave_team():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    db = get_db()
    db.execute("UPDATE kids SET team_id=NULL WHERE id=?", (g.kid_id,))
    dbmod.commit_and_sync(db)
    return jsonify({"ok": True})


@app.route("/api/teams/me", methods=["GET"])
@require_family_session
def my_team():
    if not g.kid_id:
        return jsonify({"error": "kid login required"}), 403
    db = get_db()
    kid = dbmod.fetchone(db.execute("SELECT team_id FROM kids WHERE id=?", (g.kid_id,)))
    if not kid or not kid["team_id"]:
        return jsonify({"team": None})
    team = dbmod.fetchone(db.execute("SELECT * FROM teams WHERE id=?", (kid["team_id"],)))
    if not team:
        # Team was somehow deleted out from under this kid -- treat as
        # "not on a team" rather than erroring.
        return jsonify({"team": None})
    # The one deliberate cross-family read in this codebase: every other
    # query in app.py scopes to g.family_id, but a team leaderboard is
    # exactly the point here. Only handle + lifetime points leave this
    # query -- no name, email, family_id, or pin.
    leaderboard = dbmod.fetchall(db.execute(
        """SELECT k.handle AS handle,
                  COALESCE(SUM(CASE WHEN s.status='approved' THEN s.points ELSE 0 END), 0) AS points
           FROM kids k LEFT JOIN submissions s ON s.kid_id = k.id
           WHERE k.team_id=?
           GROUP BY k.id
           ORDER BY points DESC""",
        (team["id"],),
    ))
    return jsonify({
        "team": {
            "id": team["id"],
            "name": team["name"],
            "code": team["code"],
            "goalPoints": team["goal_points"],
            "leaderboard": [{"handle": r["handle"], "points": r["points"]} for r in leaderboard],
        }
    })


if __name__ == "__main__":
    init_db()
    # 0.0.0.0 so other devices on the same wifi (like an iPad) can reach it via this machine's LAN IP.
    app.run(host="0.0.0.0", port=5000, debug=False)
