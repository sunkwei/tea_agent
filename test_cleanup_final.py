import os

def test_cleanup_final():
    """Remove the cleanup script itself"""
    path = r"C:\Users\Hetin\work\git\tea_agent\test_cleanup_winget.py"
    if os.path.exists(path):
        os.remove(path)
        print(f"Removed: test_cleanup_winget.py")
    else:
        print("Not found")

if __name__ == "__main__":
    test_cleanup_final()
