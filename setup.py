from setuptools import setup, find_packages

setup(
    name="imagebaker",
    version="0.0.1",
    packages=find_packages(),  # Automatically finds all packages
    install_requires=[
        "numpy",
        "matplotlib",
        "opencv-python",
        "black",
        "pydantic",
        "flake8",
        "PySide6",
    ],
    entry_points={
        "console_scripts": [
            "imagebaker=imagebaker.app:main",
        ],
    },
    author="Ramkrishna Acharya",
    author_email="qramkrishna@gmail.com",
    description="A package for baking images.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/q-viper/Image-Baker",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
)
