"""
Example baking configuration file for ImageBaker CLI.

Usage:
    imagebaker bake from-config examples/bake_config.py
"""

bake_config = {
    # List of layers to composite
    'layers': [
        {
            'file': 'assets/desk.png',
            'position': (0, 0),
            'opacity': 1.0,
            'scale': 1.0,
            'rotation': 0,
            'visible': True
        },
        {
            'file': 'assets/pen.png',
            'position': (100, 100),
            'opacity': 0.8,
            'scale': 0.5,
            'rotation': 15,
            'visible': True
        },
        {
            'file': 'assets/me.jpg',
            'position': (200, 50),
            'opacity': 0.6,
            'scale': 0.3,
            'rotation': -10,
            'visible': True
        },
    ],
    
    # Output file
    'output': 'assets/exports/baked_from_config.png',
}
