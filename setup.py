from setuptools import setup

setup(
    name="imagebaker",
    version="0.0.1",
    packages=["imagebaker"],
    install_requires=[
        "numpy",
        "matplotlib",
        "opencv-python",
        "black",
        "pydantic",
        "pillow",
        "flake8",
        "anytree",
    ],
    author="Ramkrishna Acharya",
    author_email="qramkrishna@gmail.com",
    description="A package for baking images.",
    url="https://github.com/q-viper/Image-Baker",
)
