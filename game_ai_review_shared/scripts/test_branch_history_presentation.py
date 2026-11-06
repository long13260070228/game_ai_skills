import unittest
import report
from test_report_presentation import document


class BranchHistoryPresentationTests(unittest.TestCase):
    def test_single_branch_does_not_present_a_fake_comparison(self):
        doc = document()
        doc.update(review_kind="branch_history", baseline="不适用（单分支审查）")
        for finding in doc["findings"]:
            finding["origin"] = "unknown"
        html = report.render(doc, "review")
        markdown = report.markdown(doc)
        self.assertIn("被审分支", html)
        self.assertIn("单分支现存问题", html)
        self.assertNotIn("确定问题归因统计", html)
        self.assertIn("单分支审查不推断问题引入时间", markdown)
        self.assertNotIn("本次新增Bug", markdown)

    def test_existing_comparison_presentation_stays_available(self):
        html = report.render(document(), "review")
        self.assertIn("目标分支", html)
        self.assertIn("基线分支", html)
        self.assertIn("确定问题归因统计", html)


if __name__ == "__main__":
    unittest.main()
