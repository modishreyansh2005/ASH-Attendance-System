import unittest
import json
import sqlite3
from app import app
import database

class TestParentPortal(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_parents_landing_unauthenticated(self):
        """When not logged in, /parents should show the Welcome & Login page."""
        response = self.client.get('/parents')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Parent Portal", content)
        self.assertIn("Parent &amp; Guardian Sign In", content)
        self.assertIn("student_id", content)
        self.assertIn("phone_or_dob", content)
        print("[PASS] GET /parents unauthenticated -> 200 OK (Welcome & Login page displayed)")

    def test_parents_login_invalid(self):
        """Invalid credentials should reject and redirect back with flash message."""
        response = self.client.post('/parents/login', data={
            'student_id': 'NON_EXISTENT_ID',
            'phone_or_dob': '0000000000'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Authentication failed", content)
        print("[PASS] POST /parents/login invalid credentials -> Rejected with flash warning")

    def test_parents_login_valid(self):
        """Valid credentials (student_id + phone) should authenticate and load dashboard."""
        response = self.client.post('/parents/login', data={
            'student_id': 'STU-1001',
            'phone_or_dob': '9054620347'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Yesha", content)
        self.assertIn("STU-1001", content)
        self.assertIn("Attendance Rate", content)
        self.assertIn("October", content)
        print("[PASS] POST /parents/login valid credentials -> Authenticated and Dashboard loaded")

    def test_parents_dashboard_features(self):
        """Verify that dashboard features: Calendar, Exams, Leaves, WhatsApp alerts render."""
        # Log in via quick login
        response = self.client.get('/parents/quick-login/STU-1001', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')

        # 1. Profile information
        self.assertIn("Yesha", content)
        self.assertIn("Grade 12", content)

        # 2. Live Today Status
        self.assertIn("Today:", content)

        # 3. Monthly Calendar
        self.assertIn("cal-grid", content)
        self.assertIn("cal-month-title", content)

        # 4. Exam results
        self.assertIn("Mathematics", content)
        self.assertIn("Exam Results &amp; Class Rank", content)

        # 5. Monthly Holidays feature placed after Daily Register
        self.assertIn("nav-holidays", content)
        self.assertIn("ptab-holidays", content)
        self.assertIn("Monthly Holidays &amp; School Closures", content)

        # Check ordering in sidebar: nav-history comes before nav-holidays
        history_pos = content.find('id="nav-history"')
        holidays_pos = content.find('id="nav-holidays"')
        exams_pos = content.find('id="nav-exams"')
        self.assertTrue(history_pos < holidays_pos < exams_pos, "nav-holidays must be placed after nav-history in sidebar")

        # 6. Online Leave Application and SMS/WhatsApp removed per user request
        self.assertNotIn("Submit Online Student Absence / Leave Note", content)
        self.assertNotIn("nav-leaves", content)
        self.assertNotIn("School SMS &amp; WhatsApp Notifications", content)
        self.assertNotIn("nav-notices", content)

        # 7. Sign Out button (Print Slip removed per user request)
        self.assertIn("Sign Out", content)
        self.assertNotIn("Print Slip", content)

        print("[PASS] GET /parents/dashboard -> Verified Monthly Holidays placed after Daily Register")

    def test_monthly_holidays_tab(self):
        """Test verifying Monthly Holidays tab opens and displays holiday directory."""
        self.client.get('/parents/quick-login/STU-1001')
        response = self.client.get('/parents/dashboard?tab=holidays', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn('id="ptab-holidays" class="tab-content-panel active"', content)
        self.assertIn("Republic Day", content)
        self.assertIn("Gandhi Jayanti", content)
        self.assertNotIn("ptab-leave", content)
        self.assertNotIn("ptab-notices", content)
        print("[PASS] Monthly Holidays tab verified active with holiday directory")
        print("[PASS] Leave and SMS/WhatsApp tabs verified removed from dashboard")

    def test_parents_logout(self):
        """Test signing out of the parent portal."""
        self.client.get('/parents/quick-login/STU-1001')
        response = self.client.get('/parents/logout', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("You have been signed out", content)
        self.assertIn("Parent &amp; Guardian Sign In", content)
        print("[PASS] GET /parents/logout -> Session cleared and returned to welcome login")

    def test_calendar_month_navigation(self):
        """Test switching calendar months via query parameters."""
        self.client.get('/parents/quick-login/STU-1001')
        response = self.client.get('/parents/dashboard?year=2026&month=9')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("September 2026", content)
        print("[PASS] Calendar Month Navigation (?year=2026&month=9) -> Successfully rendered September")

    def test_parents_grade_wise_results(self):
        """Verify grade-wise exam results view in the Parent Portal for Grade 12 students."""
        # 1. Log in as parent of STU-1001 (Yesha - Grade 12)
        self.client.get('/parents/quick-login/STU-1001')
        response = self.client.get('/parents/dashboard?tab=results', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')

        # Check ptab-results is active
        self.assertIn('id="ptab-results" class="tab-content-panel active"', content)
        # Check Grade 12 results are displayed
        self.assertIn("Grade 12", content)
        self.assertIn("Isolated to <strong>Grade 12</strong>", content)
        self.assertIn("Student Rank &amp; Evaluation List", content)
        self.assertIn("Your Child", content)
        # Check Class Division chips are present
        self.assertIn("Class Division:", content)
        self.assertIn("Grade 12", content)
        self.assertIn("Grade 11", content)
        self.assertIn("All Classes", content)
        # Check Grade 12 exam subjects are listed
        self.assertIn("Mathematics", content)

        # 2. Switch to Grade 11 to test grade-wise isolation
        response_g11 = self.client.get('/parents/dashboard?tab=results&grade=Grade 11', follow_redirects=True)
        self.assertEqual(response_g11.status_code, 200)
        content_g11 = response_g11.data.decode('utf-8')
        self.assertIn("Isolated to <strong>Grade 11</strong>", content_g11)
        print("[PASS] Grade-wise exam results verified: Grade 12 default & grade isolation working cleanly")

    def test_parents_results_pagination(self):
        """Verify 10-student pagination in the parent portal results section."""
        # 1. Log in as parent of STU-1001 (Yesha - Grade 12 has 30 total records)
        self.client.get('/parents/quick-login/STU-1001')

        # Page 1
        resp_p1 = self.client.get('/parents/dashboard?tab=results&page=1', follow_redirects=True)
        self.assertEqual(resp_p1.status_code, 200)
        c1 = resp_p1.data.decode('utf-8')
        self.assertIn("10 students per page", c1)
        self.assertIn("Showing <strong style=\"color:#0f172a;\">1</strong> &ndash; <strong style=\"color:#0f172a;\">10</strong> of <strong style=\"color:#0f172a;\">30</strong> students", c1)
        self.assertIn("Page <strong style=\"color:#0f172a;\">1</strong> of <strong style=\"color:#0f172a;\">3</strong>", c1)
        self.assertIn("Next", c1)
        # Exactly 10 rows loaded
        self.assertEqual(c1.count('class="res-row'), 10)

        # Page 2
        resp_p2 = self.client.get('/parents/dashboard?tab=results&page=2', follow_redirects=True)
        self.assertEqual(resp_p2.status_code, 200)
        c2 = resp_p2.data.decode('utf-8')
        self.assertIn("Showing <strong style=\"color:#0f172a;\">11</strong> &ndash; <strong style=\"color:#0f172a;\">20</strong> of <strong style=\"color:#0f172a;\">30</strong> students", c2)
        self.assertIn("Page <strong style=\"color:#0f172a;\">2</strong> of <strong style=\"color:#0f172a;\">3</strong>", c2)
        self.assertIn("Previous", c2)
        self.assertIn("Next", c2)
        self.assertEqual(c2.count('class="res-row'), 10)

        # Page 3
        resp_p3 = self.client.get('/parents/dashboard?tab=results&page=3', follow_redirects=True)
        self.assertEqual(resp_p3.status_code, 200)
        c3 = resp_p3.data.decode('utf-8')
        self.assertIn("Showing <strong style=\"color:#0f172a;\">21</strong> &ndash; <strong style=\"color:#0f172a;\">30</strong> of <strong style=\"color:#0f172a;\">30</strong> students", c3)
        self.assertIn("Page <strong style=\"color:#0f172a;\">3</strong> of <strong style=\"color:#0f172a;\">3</strong>", c3)
        self.assertIn("Previous", c3)
        self.assertEqual(c3.count('class="res-row'), 10)

        # Check that accessing ?page=2 without explicit tab param automatically activates results tab
        resp_direct = self.client.get('/parents/dashboard?page=2', follow_redirects=True)
        self.assertEqual(resp_direct.status_code, 200)
        c_direct = resp_direct.data.decode('utf-8')
        self.assertIn('id="ptab-results" class="tab-content-panel active"', c_direct)

        print("[PASS] Pagination in Parent Results: 10 students per page verified across Pages 1, 2, 3")

if __name__ == '__main__':
    unittest.main()


