"""String and text helpers."""


def pluralize(word: str, count: int, plural: str = "", hide_count: bool = False) -> str:
    """Generate the pluralized form of a word based on the given count.

    This function determines whether a word should be in singular or plural form
    depending on the count provided. An optional custom plural form can be supplied.
    Additionally, the count can be hidden from the final output if specified.

    Args:
        word (str): The base word to pluralize.
        count (int): The count that determines singular or plural form.
        plural (str, optional): Custom plural form to use. Defaults to adding 's'.
        hide_count (bool, optional): Indicates whether to hide the count in the output.
            Defaults to False.

    Returns:
        str: The singular or pluralized word, optionally preceded by the count.

    """
    plural = plural or f"{word}s"
    word = word if count == 1 else plural

    return word if hide_count else f"{count} {word}"
