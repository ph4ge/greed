#!/usr/bin/env python3
import os

if __package__:
    from . import common
else:
    import common


DEBUG = False


def test_phi():
    common.run_test(target_dir=f"{os.path.dirname(__file__)}/test_phi",
                    debug=DEBUG)


if __name__ == "__main__":
    common.setup_logging()
    args = common.parse_args()

    DEBUG = args.debug
    test_phi()
