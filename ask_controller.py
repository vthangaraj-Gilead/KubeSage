import json
import sys

from controller import process_question
from response_formatter import format_response


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python3.11 ask_controller.py "Why is crashloop-demo failing?"')
        print('   or: python3.11 ask_controller.py --json "Why is crashloop-demo failing?"')
        return

    json_mode = False
    args = sys.argv[1:]

    if args and args[0] == "--json":
        json_mode = True
        args = args[1:]

    question = " ".join(args).strip()
    if not question:
        print("Question is required.")
        return

    result = process_question(question)

    if json_mode:
        print(json.dumps(result, indent=2))
    else:
        print(format_response(result))


if __name__ == "__main__":
    main()
