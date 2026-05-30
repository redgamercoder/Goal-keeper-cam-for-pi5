from setuptools import setup, find_packages

setup(
    name="goalkeeper-cam",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "opencv-python-headless>=4.9",
        "ultralytics>=8.2",
        "flask>=3.0",
        "numpy>=1.26",
    ],
    entry_points={
        "console_scripts": [
            "goalkeeper-cam=goalkeeper_cam.__main__:main",
        ],
    },
    python_requires=">=3.11",
)
