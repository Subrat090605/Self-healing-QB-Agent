"""seed/bank.py — Generation of the 56 questions (quant, logical, verbal).

Implements SPEC §5.1, §5.2, §5.3.
- 36 quant + 12 logical generated from programmatic templates with computed answers
  and plausible distractors.
- 8 verbal handwritten (unambiguous).
- Planted defects P1-P5, decoys, and lowN valid item.
"""

from typing import Any


def get_all_questions() -> list[dict[str, Any]]:
    """Return all 56 questions with metadata and IRT parameters."""
    questions: list[dict[str, Any]] = []

    # -------------------------------------------------------------------------
    # 36 Quant Questions (Q001 - Q036)
    # -------------------------------------------------------------------------

    # Q001: Percentages - original price
    # A coat was sold for $180 after a 25% discount. What was the original price?
    # x * 0.75 = 180 => x = 240
    questions.append({
        "id": "Q001",
        "category": "quant",
        "stem": "A winter coat is sold for $180 after a 25% discount on its original price. What was the original price of the coat?",
        "options": {"A": "$240", "B": "$225", "C": "$215", "D": "$200"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": 0.1,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q002: Percentages - profit percentage
    # An article bought for $80 is sold for $100. Profit = 20/80 = 25%.
    questions.append({
        "id": "Q002",
        "category": "quant",
        "stem": "A merchant buys a gadget for $80 and sells it for $100. What is the merchant's profit percentage on the cost price?",
        "options": {"A": "20%", "B": "25%", "C": "30%", "D": "15%"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.4,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q003: Percentages - successive change
    # Price increases by 20% then decreases by 10%. 1.2 * 0.9 = 1.08 -> net 8% increase.
    questions.append({
        "id": "Q003",
        "category": "quant",
        "stem": "The price of a share increases by 20% on Monday and falls by 10% on Tuesday. What is the net percentage change from the initial price?",
        "options": {"A": "10% increase", "B": "5% increase", "C": "8% increase", "D": "12% increase"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q004: Percentages - part of total
    # In a school of 600 students, 45% are boys. How many girls are there? 600 * 0.55 = 330
    questions.append({
        "id": "Q004",
        "category": "quant",
        "stem": "In an academy of 600 students, 45% are boys. How many female students are enrolled in the academy?",
        "options": {"A": "270", "B": "310", "C": "350", "D": "330"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q005: [P1] Speed-distance - PLANTED WRONG KEY
    # Train 72 km/h crosses 200m platform in 25s.
    # 72 km/h = 20 m/s. 20 * 25 = 500m. Train length = 500 - 200 = 300m.
    # True correct: B (300 m). Stored key: D (500 m).
    questions.append({
        "id": "Q005",
        "category": "quant",
        "stem": "A train running at a uniform speed of 72 km/h passes completely across a 200-meter-long platform in 25 seconds. What is the length of the train?",
        "options": {"A": "250 meters", "B": "300 meters", "C": "350 meters", "D": "500 meters"},
        "key": "D",  # Planted wrong key (forgot to subtract platform length)
        "true_correct": "B",
        "alternate_valid": None,
        "label": "planted_wrong_key",
        "irt_a": 1.5,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "D",
    })

    # Q006: Speed-distance - relative speed opposite directions
    # Two cars 300 km apart travel towards each other at 60 km/h and 40 km/h. Meet in 300 / 100 = 3 hours.
    questions.append({
        "id": "Q006",
        "category": "quant",
        "stem": "Two cars start simultaneously towards each other from two towns 300 km apart at speeds of 60 km/h and 40 km/h. How many hours will they take to meet?",
        "options": {"A": "3.0 hours", "B": "2.5 hours", "C": "3.5 hours", "D": "5.0 hours"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.2,
        "irt_c": 0.2,
        "tempting_distractor": "D",
    })

    # Q007: Speed-distance - average speed
    # Outbound at 60 km/h, return at 40 km/h. Avg = 2*60*40 / 100 = 48 km/h.
    questions.append({
        "id": "Q007",
        "category": "quant",
        "stem": "A commuter drives to work at an average speed of 60 km/h and returns along the identical route at 40 km/h. What is the average speed for the round trip?",
        "options": {"A": "50 km/h", "B": "48 km/h", "C": "45 km/h", "D": "52 km/h"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.5,
        "irt_b": 0.4,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q008: Speed-distance - train crossing pole
    # Train 150m at 54 km/h crosses a pole. 54 km/h = 15 m/s. 150 / 15 = 10 s.
    questions.append({
        "id": "Q008",
        "category": "quant",
        "stem": "A train 150 meters long is travelling at a constant speed of 54 km/h. How many seconds does it take to pass a stationary telegraph pole?",
        "options": {"A": "8 seconds", "B": "12 seconds", "C": "10 seconds", "D": "15 seconds"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.1,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q009: Ratio & Proportion - dividing amount
    # Divide $720 in ratio 3:4:5. Total parts = 12. Part = 60. Middle share (4 parts) = 240.
    questions.append({
        "id": "Q009",
        "category": "quant",
        "stem": "An inheritance of $720 is divided among three siblings in the ratio 3 : 4 : 5. What is the middle sibling's share?",
        "options": {"A": "$180", "B": "$300", "C": "$200", "D": "$240"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "C",
    })

    # Q010: Ratio & Proportion - mixture problem
    # 40L mixture of milk:water is 3:1 (30L milk, 10L water). To make ratio 2:1, add water: 30 / (10 + w) = 2/1 => 20 + 2w = 30 => w = 5L.
    questions.append({
        "id": "Q010",
        "category": "quant",
        "stem": "A 40-liter mixture contains milk and water in the ratio 3 : 1. How many liters of water must be added to make the ratio of milk to water 2 : 1?",
        "options": {"A": "5 liters", "B": "10 liters", "C": "8 liters", "D": "6 liters"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.3,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q011: Ratio & Proportion - age ratio
    # Ratio of ages of A and B is 4:5. Sum is 45. B's age = 5 * (45/9) = 25.
    questions.append({
        "id": "Q011",
        "category": "quant",
        "stem": "The ratio of the present ages of two colleagues is 4 : 5. If the sum of their present ages is 45 years, how old is the elder colleague?",
        "options": {"A": "20 years", "B": "25 years", "C": "30 years", "D": "22 years"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.7,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q012: [P3] Probability - PLANTED AMBIGUOUS (Duplicate-valid option: 1/2 vs 0.5)
    # Fair die rolled once. Even number: {2, 4, 6} = 3/6 = 1/2 = 0.5.
    # Both B (1/2) and C (0.5) are completely valid and exact!
    questions.append({
        "id": "Q012",
        "category": "quant",
        "stem": "What is the probability of rolling an even number when a standard, unbiased six-sided die is rolled once?",
        "options": {"A": "1/3", "B": "1/2", "C": "0.5", "D": "2/3"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": "C",  # Duplicate valid option
        "label": "planted_ambiguous",
        "irt_a": 1.4,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "C",
    })

    # Q013: Simple Interest
    # P = $5,000, R = 6%, T = 3 years. SI = 5000 * 6 * 3 / 100 = $900.
    questions.append({
        "id": "Q013",
        "category": "quant",
        "stem": "Calculate the simple interest on a principal deposit of $5,000 invested at an annual rate of 6% for a period of 3 years.",
        "options": {"A": "$800", "B": "$850", "C": "$900", "D": "$950"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.3,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q014: Simple Interest - rate calculation
    # A sum doubles in 8 years at simple interest. SI = P => P * R * 8 / 100 = P => R = 100 / 8 = 12.5%.
    questions.append({
        "id": "Q014",
        "category": "quant",
        "stem": "At what annual rate of simple interest will a deposited principal double itself in exactly 8 years?",
        "options": {"A": "10.0%", "B": "12.0%", "C": "15.0%", "D": "12.5%"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": 0.1,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q015: Compound Interest
    # CI on $4000 at 10% per annum for 2 years. 4000 * (1.1)^2 = 4840. CI = 4840 - 4000 = $840.
    questions.append({
        "id": "Q015",
        "category": "quant",
        "stem": "What is the compound interest on a principal of $4,000 invested for 2 years at an annual interest rate of 10% compounded annually?",
        "options": {"A": "$840", "B": "$800", "C": "$880", "D": "$920"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q016: Profit & Loss - cost price from selling price
    # Selling for $460 yields 15% profit. CP = 460 / 1.15 = $400.
    questions.append({
        "id": "Q016",
        "category": "quant",
        "stem": "By selling an item for $460, a shopkeeper gains a profit of 15% on the cost price. What was the cost price of the item?",
        "options": {"A": "$380", "B": "$400", "C": "$391", "D": "$410"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "C",
    })

    # Q017: Profit & Loss - successive discount
    # Successive discounts of 20% and 10%. Net = 1 - 0.8 * 0.9 = 1 - 0.72 = 28%.
    questions.append({
        "id": "Q017",
        "category": "quant",
        "stem": "What single discount percentage is equivalent to two successive discounts of 20% and 10% on an item's marked price?",
        "options": {"A": "30%", "B": "25%", "C": "28%", "D": "26%"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q018: Time & Work - joint work
    # A completes in 12 days, B in 24 days. 1/12 + 1/24 = 3/24 = 1/8 => 8 days.
    questions.append({
        "id": "Q018",
        "category": "quant",
        "stem": "Worker A can finish a construction task in 12 days, while Worker B requires 24 days. Working together at their respective rates, how many days will they take to complete the task?",
        "options": {"A": "6 days", "B": "10 days", "C": "9 days", "D": "8 days"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q019: Time & Work - pipes
    # Pipe A fills in 4 hours, Pipe B in 6 hours. 1/4 + 1/6 = 5/12 => 12/5 = 2.4 hours.
    questions.append({
        "id": "Q019",
        "category": "quant",
        "stem": "Pipe A can fill a water reservoir in 4 hours, and Pipe B can fill it in 6 hours. If both pipes are opened simultaneously, in how many hours will the reservoir be filled?",
        "options": {"A": "2.4 hours", "B": "2.5 hours", "C": "3.0 hours", "D": "2.0 hours"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": 0.1,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q020: Time & Work - inverse proportion
    # 15 laborers complete a trench in 12 days. How many days will 20 laborers take? 15 * 12 / 20 = 9 days.
    questions.append({
        "id": "Q020",
        "category": "quant",
        "stem": "If 15 workers can dig a trench in 12 days working at the same pace, how many days will 20 workers take to dig the same trench?",
        "options": {"A": "8 days", "B": "9 days", "C": "10 days", "D": "7 days"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.4,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q021: Time & Work - subtraction
    # A and B together take 6 days. A alone takes 10 days. 1/6 - 1/10 = 2/30 = 1/15 => B takes 15 days.
    questions.append({
        "id": "Q021",
        "category": "quant",
        "stem": "Alice and Bob working together can finish a report in 6 days. If Alice alone can finish it in 10 days, how many days would Bob take working alone?",
        "options": {"A": "12 days", "B": "14 days", "C": "15 days", "D": "16 days"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.3,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q022: Averages - consecutive numbers
    # Average of 5 consecutive odd numbers is 27. Numbers: 23, 25, 27, 29, 31. Largest is 31.
    questions.append({
        "id": "Q022",
        "category": "quant",
        "stem": "The average of 5 consecutive odd integers is 27. What is the value of the largest of these 5 integers?",
        "options": {"A": "29", "B": "33", "C": "35", "D": "31"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.3,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q023: Averages - new entrant
    # Average weight of 19 athletes is 70 kg. When coach joins, average increases to 71 kg.
    # Total = 20 * 71 - 19 * 70 = 1420 - 1330 = 90 kg.
    questions.append({
        "id": "Q023",
        "category": "quant",
        "stem": "The average weight of 19 athletes is 70 kg. If the coach joins the group, the new average weight becomes 71 kg. What is the weight of the coach?",
        "options": {"A": "90 kg", "B": "89 kg", "C": "85 kg", "D": "91 kg"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q024: Averages - cricket batsman
    # Batsman has avg 40 in 10 innings. Scores 95 in 11th. New avg = (400 + 95) / 11 = 495 / 11 = 45.
    questions.append({
        "id": "Q024",
        "category": "quant",
        "stem": "A batsman has a scoring average of 40 runs across 10 completed innings. In his 11th innings, he scores 95 runs. What is his new batting average?",
        "options": {"A": "44 runs", "B": "45 runs", "C": "46 runs", "D": "48 runs"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q025: [Decoy Hard 1] Repeated dilution - DECOY HARD
    # 100L pure milk. 10L removed and replaced with water, repeated 3 times total.
    # Milk remaining = 100 * (1 - 0.1)^3 = 100 * 0.729 = 72.9 liters.
    questions.append({
        "id": "Q025",
        "category": "quant",
        "stem": "A container originally holds 100 liters of pure milk. Exactly 10 liters are removed and replaced with water. This entire replacement process is performed a total of 3 times. How many liters of pure milk remain in the container?",
        "options": {"A": "70.0 liters", "B": "72.9 liters", "C": "75.0 liters", "D": "81.0 liters"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "decoy_hard",
        "irt_a": 1.6,
        "irt_b": 1.7,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q026: Algebra - linear equation
    # 5x - 17 = 38 => 5x = 55 => x = 11.
    questions.append({
        "id": "Q026",
        "category": "quant",
        "stem": "If 5x - 17 = 38, what is the value of x?",
        "options": {"A": "9", "B": "10", "C": "11", "D": "12"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.0,
        "irt_b": -0.8,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q027: Algebra - sum and difference
    # Sum of two numbers is 64 and difference is 16. Larger = (64 + 16)/2 = 40.
    questions.append({
        "id": "Q027",
        "category": "quant",
        "stem": "The sum of two real numbers is 64, and their positive difference is 16. What is the value of the larger number?",
        "options": {"A": "36", "B": "48", "C": "42", "D": "40"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q028: Geometry - rectangle perimeter
    # Perimeter = 54 cm, width = 12 cm. 2(L + 12) = 54 => L + 12 = 27 => L = 15 cm.
    questions.append({
        "id": "Q028",
        "category": "quant",
        "stem": "The perimeter of a rectangular courtyard is 54 meters, and its width is 12 meters. What is the length of the courtyard?",
        "options": {"A": "15 meters", "B": "18 meters", "C": "21 meters", "D": "16 meters"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.6,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q029: Number Theory - LCM
    # LCM of 15 and 25 is 75.
    questions.append({
        "id": "Q029",
        "category": "quant",
        "stem": "What is the least common multiple (LCM) of the positive integers 15 and 25?",
        "options": {"A": "50", "B": "75", "C": "100", "D": "125"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.4,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q030: [Decoy Easy 1] Basic arithmetic - DECOY EASY
    # 10% of 250 is 25.
    questions.append({
        "id": "Q030",
        "category": "quant",
        "stem": "What is 10% of 250?",
        "options": {"A": "20", "B": "25", "C": "30", "D": "50"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "decoy_easy",
        "irt_a": 1.2,
        "irt_b": -2.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q031: Number Theory - GCD
    # GCD of 48 and 72 is 24.
    questions.append({
        "id": "Q031",
        "category": "quant",
        "stem": "What is the greatest common divisor (GCD) of 48 and 72?",
        "options": {"A": "12", "B": "16", "C": "24", "D": "36"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q032: Algebra - difference of squares
    # 35^2 - 25^2 = (35-25)(35+25) = 10 * 60 = 600.
    questions.append({
        "id": "Q032",
        "category": "quant",
        "stem": "Evaluate the exact numerical expression: 35^2 - 25^2.",
        "options": {"A": "500", "B": "550", "C": "650", "D": "600"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.1,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q033: Probability - marble draw
    # Bag has 5 red, 7 green, 8 blue (total 20). P(green) = 7/20 = 0.35.
    questions.append({
        "id": "Q033",
        "category": "quant",
        "stem": "An urn contains 5 red balls, 7 green balls, and 8 blue balls. If one ball is chosen at random, what is the probability that it is green?",
        "options": {"A": "7/20", "B": "1/4", "C": "2/5", "D": "8/20"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.1,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q034: Work & Rates - multi-person rate
    # 4 workers pack 160 boxes in 2 hours => rate = 160 / (4 * 2) = 20 boxes/worker-hr.
    # 6 workers in 3 hours pack 6 * 3 * 20 = 360 boxes.
    questions.append({
        "id": "Q034",
        "category": "quant",
        "stem": "If 4 warehouse workers can pack 160 parcel boxes in 2 hours, how many parcel boxes can 6 workers pack in 3 hours at the same constant rate?",
        "options": {"A": "320 boxes", "B": "360 boxes", "C": "340 boxes", "D": "400 boxes"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q035: Geometry - triangle area
    # Base = 16 cm, height = 9 cm. Area = 0.5 * 16 * 9 = 72 cm^2.
    questions.append({
        "id": "Q035",
        "category": "quant",
        "stem": "What is the area of a right-angled triangle having a base of 16 cm and an altitude (height) of 9 cm?",
        "options": {"A": "144 cm^2", "B": "81 cm^2", "C": "72 cm^2", "D": "64 cm^2"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q036: Arithmetic puzzle - head and feet
    # Farm has chickens and cows. 30 heads, 84 legs.
    # c + w = 30; 2c + 4w = 84 => 2w = 24 => w = 12 cows, c = 18 chickens.
    questions.append({
        "id": "Q036",
        "category": "quant",
        "stem": "A farmer counts 30 animal heads and 84 animal legs among his chickens (2 legs) and cows (4 legs). How many chickens are on the farm?",
        "options": {"A": "12", "B": "15", "C": "16", "D": "18"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.5,
        "irt_b": 0.3,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # -------------------------------------------------------------------------
    # 12 Logical Questions (Q037 - Q048)
    # -------------------------------------------------------------------------

    # Q037: Number Series - AP
    # 5, 11, 17, 23, ? (+6 each step) => 29.
    questions.append({
        "id": "Q037",
        "category": "logical",
        "stem": "What is the next number in the arithmetic progression: 5, 11, 17, 23, ?",
        "options": {"A": "29", "B": "28", "C": "30", "D": "31"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q038: [P2] Letter Series - PLANTED WRONG KEY
    # B, E, H, K, N, ? (+3 letters: B(2)->E(5)->H(8)->K(11)->N(14)->Q(17)).
    # True correct: B (Q). Stored key: A (P).
    questions.append({
        "id": "Q038",
        "category": "logical",
        "stem": "What is the next letter in the alphabetical series: B, E, H, K, N, ?",
        "options": {"A": "P", "B": "Q", "C": "R", "D": "O"},
        "key": "A",  # Planted wrong key (attractive off-by-one distractor)
        "true_correct": "B",
        "alternate_valid": None,
        "label": "planted_wrong_key",
        "irt_a": 1.5,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q039: Number Series - Squares
    # 4, 9, 16, 25, 36, ? (2^2, 3^2, 4^2, 5^2, 6^2, 7^2 = 49).
    questions.append({
        "id": "Q039",
        "category": "logical",
        "stem": "Identify the next number in the sequence of squares: 4, 9, 16, 25, 36, ?",
        "options": {"A": "48", "B": "45", "C": "49", "D": "50"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q040: Number Series - Cubes
    # 1, 8, 27, 64, ? (1^3, 2^3, 3^3, 4^3, 5^3 = 125).
    questions.append({
        "id": "Q040",
        "category": "logical",
        "stem": "What is the next number in the integer sequence: 1, 8, 27, 64, ?",
        "options": {"A": "100", "B": "121", "C": "144", "D": "125"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.4,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q041: Letter Series - Skip pattern
    # A, C, F, J, ? (+2, +3, +4, +5: A(1)->C(3)->F(6)->J(10)->O(15)).
    questions.append({
        "id": "Q041",
        "category": "logical",
        "stem": "Complete the letter series: A, C, F, J, ?",
        "options": {"A": "O", "B": "N", "C": "P", "D": "M"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.1,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q042: [P4] Number Series - PLANTED AMBIGUOUS (Two readings)
    # Series: 2, 4, 8, ?
    # Reading 1: Doubling (x2, x2, x2) => 16.
    # Reading 2: Differences +2, +4, +6 => 8 + 6 = 14.
    # Options: A: 12, B: 14, C: 16, D: 18.
    # Stored key: C (16), alternate valid: B (14).
    questions.append({
        "id": "Q042",
        "category": "logical",
        "stem": "What is the next logical number in the sequence: 2, 4, 8, ?",
        "options": {"A": "12", "B": "14", "C": "16", "D": "18"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": "B",
        "label": "planted_ambiguous",
        "irt_a": 1.4,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "B",
    })

    # Q043: Coding-Decoding - Shift cipher
    # If COLD is coded as DPME (+1 to each letter), how is WARM coded?
    # W->X, A->B, R->S, M->N => XBSN.
    questions.append({
        "id": "Q043",
        "category": "logical",
        "stem": "In a certain substitution code, COLD is written as DPME. Following the exact same rule, how should the word WARM be encoded?",
        "options": {"A": "XBSN", "B": "XBTM", "C": "VZQL", "D": "XCSN"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.3,
        "irt_c": 0.2,
        "tempting_distractor": "D",
    })

    # Q044: Direction Sense
    # Walk 12 m North, then turn right and walk 5 m East.
    # Distance from start = sqrt(12^2 + 5^2) = sqrt(169) = 13 m.
    questions.append({
        "id": "Q044",
        "category": "logical",
        "stem": "Starting from point O, a hiker walks 12 meters due North, turns 90 degrees right and walks 5 meters due East. What is the straight-line distance from the hiker's current position back to point O?",
        "options": {"A": "17 meters", "B": "13 meters", "C": "15 meters", "D": "14 meters"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.1,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q045: [P5] Planted Non-discriminating item - PLANTED NONDISC
    # Badly posed / irrelevant item; P(correct) = 0.40 regardless of ability.
    questions.append({
        "id": "Q045",
        "category": "logical",
        "stem": "In an experiment with an opaque bag containing an undisclosed distribution of colored tokens, which token is guaranteed to be drawn on the very first blind attempt?",
        "options": {"A": "Red token", "B": "Blue token", "C": "Green token", "D": "Yellow token"},
        "key": "A",
        "true_correct": "A",
        "alternate_valid": None,
        "label": "planted_nondisc",
        "irt_a": 0.0,
        "irt_b": 0.0,
        "irt_c": 0.40,
        "tempting_distractor": "B",
    })

    # Q046: Syllogism - Deductive logic
    # Premise 1: All squares are rectangles. Premise 2: All rectangles are quadrilaterals.
    # Valid deduction: All squares are quadrilaterals.
    questions.append({
        "id": "Q046",
        "category": "logical",
        "stem": "Given two true premises: 'All squares are rectangles' and 'All rectangles are quadrilaterals', which of the following logical conclusions is necessarily valid?",
        "options": {
            "A": "All quadrilaterals are squares",
            "B": "No quadrilaterals are rectangles",
            "C": "All squares are quadrilaterals",
            "D": "Some squares are not quadrilaterals"
        },
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q047: [Decoy Hard 2] Complex Seating Arrangement - DECOY HARD
    # 5 delegates P, Q, R, S, T sit in row facing North. T extreme left (pos 1), Q extreme right (pos 5).
    # R immediately right of S (pos 3, 4). P cannot sit next to Q (so P at pos 2).
    # Who sits immediately right of P? Delegate S at pos 3.
    questions.append({
        "id": "Q047",
        "category": "logical",
        "stem": "Five diplomats P, Q, R, S, and T sit in a single row facing North. T sits at the extreme left, and Q sits at the extreme right. R sits immediately to the right of S. If P and Q cannot sit adjacent to each other, which diplomat sits immediately to the right of P?",
        "options": {"A": "R", "B": "S", "C": "T", "D": "Q"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "decoy_hard",
        "irt_a": 1.6,
        "irt_b": 1.7,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q048: Blood Relations
    # Pointing to a gentleman, David says: 'He is the only son of my father's father.'
    # Father's father = Grandfather. Only son of grandfather = David's father.
    questions.append({
        "id": "Q048",
        "category": "logical",
        "stem": "Pointing to a gentleman, David said: 'He is the only son of my father's father.' How is the gentleman related to David?",
        "options": {"A": "Uncle", "B": "Brother", "C": "Cousin", "D": "Father"},
        "key": "D",
        "true_correct": "D",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.1,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # -------------------------------------------------------------------------
    # 8 Verbal Questions (Q049 - Q056) - Handwritten, Unambiguous
    # -------------------------------------------------------------------------

    # Q049: Analogy - Geography / Natural features
    # OASIS : DESERT :: ISLAND : OCEAN
    questions.append({
        "id": "Q049",
        "category": "verbal",
        "stem": "Complete the analogy based on the relationship between the words: OASIS is to DESERT as ISLAND is to:",
        "options": {"A": "Peninsula", "B": "Mountain", "C": "Ocean", "D": "Forest"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.3,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q050: [Decoy Easy 2] Analogy - Basic biological need - DECOY EASY
    # WATER : THIRST :: FOOD : HUNGER
    questions.append({
        "id": "Q050",
        "category": "verbal",
        "stem": "Complete the analogy based on the direct relationship: WATER is to THIRST as FOOD is to:",
        "options": {"A": "Drink", "B": "Hunger", "C": "Sleep", "D": "Rest"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "decoy_easy",
        "irt_a": 1.2,
        "irt_b": -2.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q051: Analogy - Creator to Creation
    # ARCHITECT : BUILDING :: SCULPTOR : STATUE
    questions.append({
        "id": "Q051",
        "category": "verbal",
        "stem": "Select the option that best completes the analogy: ARCHITECT is to BUILDING as SCULPTOR is to:",
        "options": {"A": "Chisel", "B": "Statue", "C": "Canvas", "D": "Museum"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.6,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q052: Odd-One-Out - Classification
    # Carrot (vegetable), while Apple, Banana, Orange are fruits.
    questions.append({
        "id": "Q052",
        "category": "verbal",
        "stem": "Choose the word that does not belong in the same semantic category as the other three:",
        "options": {"A": "Apple", "B": "Banana", "C": "Carrot", "D": "Orange"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.2,
        "irt_b": -0.8,
        "irt_c": 0.2,
        "tempting_distractor": "D",
    })

    # Q053: [LowN Valid] Sentence Completion - LOW N VALID (only 12 attempts)
    # The ancient manuscript was remarkably intact, with every page preserved in pristine condition.
    questions.append({
        "id": "Q053",
        "category": "verbal",
        "stem": "Choose the word that best completes the sentence logically: The ancient manuscript was remarkably _______, with every single page preserved in pristine condition.",
        "options": {"A": "fragile", "B": "intact", "C": "fragmented", "D": "illegible"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "lowN_valid",
        "irt_a": 1.3,
        "irt_b": 0.0,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q054: Sentence Completion - Contextual vocabulary
    # Despite facing severe financial difficulties, the non-profit organization remained committed to its mission.
    questions.append({
        "id": "Q054",
        "category": "verbal",
        "stem": "Choose the word that best completes the sentence: Despite facing severe financial challenges, the hospital staff remained steadfastly _______ to providing compassionate patient care.",
        "options": {"A": "reluctant", "B": "committed", "C": "indifferent", "D": "hostile"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": -0.5,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q055: Antonym - Vocabulary
    # CANDID means truthful and direct. Opposite is DECEITFUL.
    questions.append({
        "id": "Q055",
        "category": "verbal",
        "stem": "Choose the word that is most nearly OPPOSITE in meaning to the word CANDID:",
        "options": {"A": "Honest", "B": "Frank", "C": "Deceitful", "D": "Sincere"},
        "key": "C",
        "true_correct": "C",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.4,
        "irt_b": 0.1,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    # Q056: Synonym - Vocabulary
    # PRAGMATIC means dealing with things sensibly and realistically (PRACTICAL).
    questions.append({
        "id": "Q056",
        "category": "verbal",
        "stem": "Choose the word that is most nearly SIMILAR in meaning to the word PRAGMATIC:",
        "options": {"A": "Theoretical", "B": "Practical", "C": "Idealistic", "D": "Speculative"},
        "key": "B",
        "true_correct": "B",
        "alternate_valid": None,
        "label": "clean",
        "irt_a": 1.3,
        "irt_b": 0.2,
        "irt_c": 0.2,
        "tempting_distractor": "A",
    })

    return questions
