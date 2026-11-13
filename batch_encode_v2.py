"""Command-line frontend for Cryptoleaf batch encoding."""
import argparse
from pathlib import Path
from src.batch_processor import process_batch, write_report


def main():
    parser = argparse.ArgumentParser(description="Encode images in a directory")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--message", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--quality", type=int, default=85)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    results = process_batch(args.input_dir, args.output_dir, args.message.encode("utf-8"), args.password, quality=args.quality, dry_run=args.dry_run, skip_existing=args.skip_existing)
    for r in results:
        print(f"{r.status:8} {r.image} {r.format} strength={r.strength} attempts={r.attempts} {r.error}")
    if not args.dry_run:
        report = write_report(results, args.output_dir / "batch_report.csv")
        print(f"Report: {report}")
    if args.dry_run:
        print(f"Planned: {sum(r.status == 'DRY_RUN' for r in results)}/{len(results)} images; 0 processed")
    else:
        print(f"Completed: {sum(r.status == 'OK' for r in results)}/{len(results)} OK")


if __name__ == "__main__":
    main()
