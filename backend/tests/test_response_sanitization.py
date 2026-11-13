import unittest

from app.main import extract_user_facing_reply


class UserFacingReplyTests(unittest.TestCase):
    def test_keeps_clean_final_answer(self):
        self.assertEqual(
            extract_user_facing_reply("Hello Founder. I can help plan the project."),
            "Hello Founder. I can help plan the project.",
        )

    def test_extracts_text_after_complete_think_block(self):
        self.assertEqual(
            extract_user_facing_reply("<think>private draft</think>Here is the answer."),
            "Here is the answer.",
        )

    def test_rejects_unclosed_think_block(self):
        self.assertIsNone(extract_user_facing_reply("<think>private draft without a closing tag"))

    def test_rejects_unmatched_closing_think_tag(self):
        self.assertIsNone(extract_user_facing_reply("private draft</think>"))

    def test_rejects_internal_planning_narration(self):
        self.assertIsNone(
            extract_user_facing_reply(
                "Okay, the user wants me to introduce myself. Mental note: be concise."
            )
        )

    def test_rejects_reflection_markers(self):
        self.assertIsNone(
            extract_user_facing_reply(
                "The biggest risk: I should be super precise. Final check before responding."
            )
        )


if __name__ == "__main__":
    unittest.main()
