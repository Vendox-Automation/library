import pytest
import pandas as pd
from vdx_auto_utils.data_utils import split_dataframe


class TestSplitDataframe:

    def setup_method(self):
        self.df = pd.DataFrame({
            "name": ["Alice", "Bob", "Charlie", "Diana"],
            "score": [90, 45, 80, 30]
        })

    def test_extracts_rows_where_mask_is_true(self):
        mask = self.df["score"] >= 80
        extracted, _ = split_dataframe(self.df, mask)
        assert list(extracted["name"]) == ["Alice", "Charlie"]

    def test_remaining_rows_where_mask_is_false(self):
        mask = self.df["score"] >= 80
        _, remaining = split_dataframe(self.df, mask)
        assert list(remaining["name"]) == ["Bob", "Diana"]

    def test_extracted_and_remaining_cover_all_rows(self):
        mask = self.df["score"] >= 50
        extracted, remaining = split_dataframe(self.df, mask)
        assert len(extracted) + len(remaining) == len(self.df)

    def test_all_true_mask_returns_empty_remaining(self):
        mask = self.df["score"] > 0
        extracted, remaining = split_dataframe(self.df, mask)
        assert len(extracted) == len(self.df)
        assert len(remaining) == 0

    def test_all_false_mask_returns_empty_extracted(self):
        mask = self.df["score"] > 100
        extracted, remaining = split_dataframe(self.df, mask)
        assert len(extracted) == 0
        assert len(remaining) == len(self.df)

    def test_returns_copies_not_views(self):
        mask = self.df["score"] >= 80
        extracted, remaining = split_dataframe(self.df, mask)
        extracted.loc[extracted.index[0], "name"] = "MODIFIED"
        assert self.df.loc[0, "name"] == "Alice"  # original unchanged

    def test_empty_dataframe(self):
        empty_df = pd.DataFrame({"name": [], "score": []})
        mask = empty_df["score"] >= 80
        extracted, remaining = split_dataframe(empty_df, mask)
        assert len(extracted) == 0
        assert len(remaining) == 0