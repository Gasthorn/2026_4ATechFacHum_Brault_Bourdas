"""Point d'entrée — délègue au package calibrage/ (voir calibrage/__init__.py)."""

import sys

from calibrage import main

if __name__ == "__main__":
    main(sys.argv[1:])
