"""Table maps. Each table row: (name, seats, shape, x%, y%) on a 5:3 floor plan (x = left, y = top, centred).
Fixtures: labelled areas drawn behind the tables (x, y, w, h in %; v = vertical text, b = text at bottom).
Lub Dub Cafe is mapped from the walkthrough video, Golden Sun Restaurant from a floor-plan image, Khloe from two photos. Both are approximate:
adjust them in Manage > Tables & layout."""

GENERIC = [("T1", 2, "square", 15, 20), ("T2", 2, "square", 15, 45), ("T3", 4, "rect", 40, 20),
           ("T4", 4, "rect", 40, 45), ("T5", 6, "long", 68, 22), ("T6", 8, "long", 68, 48)]

GENERIC_FIXTURES = [
    {"label": "Entrance", "x": 97, "y": 28, "w": 3, "h": 25, "v": True},
    {"label": "Counter", "x": 76, "y": 87, "w": 24, "h": 13},
]

LAYOUTS = {
    "symmetric-demo": [
        # Left side tables (mirror of right side)
        ("TL1", 4, "rect", 20, 20), ("TL2", 4, "rect", 20, 40), ("TL3", 4, "rect", 20, 60), ("TL4", 4, "rect", 20, 80),
        # Right side tables
        ("TR1", 4, "rect", 80, 20), ("TR2", 4, "rect", 80, 40), ("TR3", 4, "rect", 80, 60), ("TR4", 4, "rect", 80, 80),
        # Center lounge tables
        ("C1", 6, "long", 50, 30), ("C2", 6, "long", 50, 70),
    ],
    "lub-dub-cafe": [
        ("T1", 4, "rect", 12, 33), ("T2", 4, "rect", 12, 76), ("T3", 4, "rect", 27, 56),   # brick-wall corner
        ("T4", 6, "long", 43, 75), ("T5", 4, "rect", 43, 40),                              # wooden tables with benches
        ("T6", 2, "square", 36, 14), ("T7", 2, "square", 48, 14), ("T8", 2, "square", 60, 14), ("T9", 2, "square", 72, 14),  # glass-edge row
        ("T10", 4, "round", 66, 52), ("T11", 2, "round", 78, 43), ("T12", 2, "round", 60, 81),
        ("T13", 2, "round", 74, 78), ("T14", 2, "round", 88, 24),                          # round tables near entrance
    ],
    "golden-sun": [  # from the supplied floor plan image (T6 = long banquet table)
        ("T1", 4, "rect", 18, 17), ("T2", 4, "rect", 39, 17), ("T3", 4, "rect", 62, 17), ("T4", 4, "rect", 83, 17),
        ("T5", 4, "rect", 18, 50), ("T6", 12, "banquet", 49, 50), ("T7", 4, "rect", 79, 50),
        ("T8", 4, "rect", 18, 85), ("T9", 4, "rect", 39, 85), ("T10", 4, "rect", 62, 85),
    ],
    "chloe": [  # from two photos of a red-trussed hall with booths and a buffet line
        ("T1", 4, "rect", 14, 16), ("T2", 4, "rect", 30, 16), ("T3", 4, "rect", 46, 16),   # red booth wall
        ("T4", 6, "long", 14, 42), ("T5", 6, "long", 14, 70), ("T6", 6, "long", 36, 45), ("T7", 6, "long", 36, 73),  # long cream tables
        ("T8", 4, "rect", 58, 40), ("T9", 4, "rect", 58, 64), ("T10", 4, "rect", 74, 40), ("T11", 4, "rect", 74, 64),  # 4-tops
        ("T12", 4, "rect", 58, 88),
    ],
}

FIXTURES = {
    "lub-dub-cafe": [
        {"label": "Indoor wall corner", "x": 0, "y": 0, "w": 22, "h": 100, "b": True},
        {"label": "Windows / garden side", "x": 22, "y": 0, "w": 78, "h": 4},
        {"label": "Entrance", "x": 97, "y": 28, "w": 3, "h": 25, "v": True},
        {"label": "Counter", "x": 76, "y": 87, "w": 24, "h": 13},
    ],
    "golden-sun": [
        {"label": "Window", "x": 0, "y": 36, "w": 3, "h": 26, "v": True},
        {"label": "Window", "x": 97, "y": 36, "w": 3, "h": 26, "v": True},
        {"label": "Reception", "x": 79, "y": 79, "w": 17, "h": 21},
        {"label": "Entrance", "x": 41, "y": 95, "w": 18, "h": 5},
    ],
    "chloe": [
        {"label": "Red booth wall", "x": 0, "y": 0, "w": 62, "h": 5},
        {"label": "Buffet / food line", "x": 88, "y": 8, "w": 12, "h": 62, "v": True},
        {"label": "Stairs to mezzanine", "x": 0, "y": 88, "w": 26, "h": 12},
        {"label": "Entrance", "x": 97, "y": 78, "w": 3, "h": 20, "v": True},
    ],
}
