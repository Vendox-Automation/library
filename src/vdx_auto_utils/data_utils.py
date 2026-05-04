import pandas as pd
from typing import Tuple


def split_dataframe(
    df: pd.DataFrame, mask: pd.Series
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Splits a DataFrame into two based on a boolean mask.

    Args:
        df: The source DataFrame.
        mask: A boolean Series aligned with the DataFrame's index.

    Returns:
        A tuple containing (extracted_df, remaining_df).
        - extracted_df: Rows where the mask is True.
        - remaining_df: Rows where the mask is False.
    """
    extracted = df[mask].copy()
    remaining = df[~mask].copy()
    return extracted, remaining
