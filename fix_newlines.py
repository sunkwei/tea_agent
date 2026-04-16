import glob
import os

# Find all python files in tea_agent/ and subdirectories
files = glob.glob("tea_agent/**/*.py", recursive=True)

count = 0
for f in files:
    with open(f, 'rb') as fp:
        content = fp.read()
        if content and not content.endswith(b'\n'):
            with open(f, 'ab') as wfp:
                wfp.write(b'\n')
            print(f"Added newline to: {f}")
            count += 1

print(f"Done. Fixed {count} files.")
