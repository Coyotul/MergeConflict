import sys


def main():
    print("[OK] Virtual environment activat cu succes!")
    print(f"Python interpreter: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")


if __name__ == "__main__":
    main()
