"""Start self-evolve and subconscious engines."""
import sys
sys.path.insert(0, r"C:\Users\Hetin\work\git\tea_agent")

from tea_agent.toolkit.toolkit_self_evolve_thread import SelfEvolveThread
from tea_agent.toolkit.toolkit_subconscious import SubconsciousEngine

# Start self-evolve thread
t = SelfEvolveThread()
t.start()
print("✓ Self-evolve thread started")

# Start subconscious engine
s = SubconsciousEngine()
s.start()
print("✓ Subconscious engine started")
