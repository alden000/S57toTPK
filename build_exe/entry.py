import multiprocessing
import sys

from s57totpk.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
