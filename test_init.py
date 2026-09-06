import sys
sys.path.insert(0, 'F:/My Son')
from Core.init_command import run_init

print("Running init...")
result = run_init()
print(f"Exit code: {result}")