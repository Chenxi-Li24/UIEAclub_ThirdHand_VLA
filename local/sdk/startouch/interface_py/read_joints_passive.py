import argparse
import subprocess
from pathlib import Path


def default_print_joints_path() -> Path:
    here = Path(__file__).resolve()
    fnl_root = here.parents[2]
    return fnl_root / "startouchlib" / "build" / "print_joints"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Passive joint reader. It does not construct SingleArm and does not enable motors."
    )
    parser.add_argument("can_interface", nargs="?", default="can0")
    parser.add_argument("--count", type=int, default=1, help="Number of samples to print. Use -1 for continuous.")
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument(
        "--print-joints-bin",
        type=Path,
        default=default_print_joints_path(),
        help="Path to startouchlib/build/print_joints",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.print_joints_bin.exists():
        raise FileNotFoundError(
            f"{args.print_joints_bin} not found. Build startouchlib first: cmake --build build -j2"
        )

    cmd = [
        str(args.print_joints_bin),
        args.can_interface,
        "--interval-ms",
        str(args.interval_ms),
    ]
    if args.count == 1:
        cmd.append("--once")
    elif args.count > 0:
        cmd.extend(["--count", str(args.count)])

    print("Passive read only. Motors are not enabled.")
    print("Command:", " ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
