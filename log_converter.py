import json
import os


def load_log_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def format_entry(label, text):
    return f"\n[{label.upper()}]\n{text.strip()}\n"


def convert_log_to_formatted_text(log_data):
    user_inputs = log_data.get("user", [])
    reasoning_outputs = log_data.get("pentestGPT", [])
    generation_outputs = log_data.get("generation", [])

    formatted_sections = []

    user_index = 0
    reasoning_index = 0
    generation_index = 0
    step = 0

    while True:
        stop = True
        # 1. Start with a user input
        if user_index < len(user_inputs):
            stop = False
            _, user_text = user_inputs[user_index]
            formatted_sections.append(format_entry("user", user_text))
            user_index += 1

        # 2. Next the reasoning ouput is needed (PTT + Memory + State generation and then task selection)
        if reasoning_index < len(reasoning_outputs):
            stop = False
            _, reasoning_text = reasoning_outputs[reasoning_index]
            formatted_sections.append(
                format_entry(f"reasoning #{step}", reasoning_text)
            )
            reasoning_index += 1

        # 3. Last part of one step is the generation session
        if generation_index < len(generation_outputs):
            stop = False
            _, generation_text = generation_outputs[generation_index]
            formatted_sections.append(
                format_entry(f"generation #{step}", generation_text)
            )
            generation_index += 1

        if stop:
            break
        step += 1

    return "\n" + "\n".join(formatted_sections)


if __name__ == "__main__":
    input_path = input(
        "Enter the path to the log file (e.g., example_log.json): "
    ).strip()
    filename_without_ext = os.path.splitext(os.path.basename(input_path))[0]
    output_path = input(
        f"Enter the desired output file name [default: {filename_without_ext}_formatted.txt]: "
    ).strip()
    if not output_path:
        output_path = filename_without_ext + "_formatted.txt"

    log_data = load_log_file(input_path)
    formatted_text = convert_log_to_formatted_text(log_data)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(formatted_text)

    print(f"Formatted output saved to: {output_path}")
