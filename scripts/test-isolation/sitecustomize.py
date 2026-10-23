"""Install the fast-test guard in Python subprocesses."""
import sys
sys.dont_write_bytecode = True
from unit_guard import install
install()
