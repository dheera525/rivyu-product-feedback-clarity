"""Realistic demo dataset for when live scraping isn't available."""


DEMO_ITEMS = [
    {"id": "demo_001", "source": "google_play", "text": "App crashes every single time I open it after the latest update. Completely unusable now.", "author": "frustrated_user", "date": "2026-03-01T10:30:00Z", "rating": 1, "metadata": {"app_version": "3.2.1", "device": "Samsung Galaxy S24"}},
    {"id": "demo_002", "source": "google_play", "text": "Keeps crashing on launch. Was working fine before the update. Please fix!", "author": "mobile_mike", "date": "2026-03-03T14:20:00Z", "rating": 1, "metadata": {"app_version": "3.2.1", "device": "Pixel 8"}},
    {"id": "demo_003", "source": "reddit", "text": "Anyone else getting crashes after the 3.2 update? App won't even open anymore.", "author": "techie42", "date": "2026-03-05T09:15:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 87}},
    {"id": "demo_004", "source": "google_play", "text": "Crash on startup after update. Reinstalling didn't help. Lost all my data.", "author": "angry_customer", "date": "2026-03-08T16:00:00Z", "rating": 1, "metadata": {"app_version": "3.2.1", "device": "OnePlus 12"}},
    {"id": "demo_005", "source": "reddit", "text": "The app crashes immediately when you try to open it. This update broke everything.", "author": "user_2026", "date": "2026-03-10T11:45:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 134}},

    {"id": "demo_006", "source": "google_play", "text": "Login OTP never arrives. I've been waiting for 20 minutes. Can't access my account.", "author": "login_issues", "date": "2026-03-02T08:00:00Z", "rating": 2, "metadata": {"app_version": "3.2.0"}},
    {"id": "demo_007", "source": "google_play", "text": "OTP code doesn't come through. Tried multiple times. Authentication is broken.", "author": "cant_login", "date": "2026-03-07T13:30:00Z", "rating": 1, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_008", "source": "reddit", "text": "Is the login system down? OTP authentication hasn't worked for me in days.", "author": "blocked_out", "date": "2026-03-12T15:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 45}},
    {"id": "demo_009", "source": "csv", "text": "Cannot login. OTP never comes. Support hasn't responded in 3 days.", "author": "support_ticket_user", "date": "2026-03-18T10:00:00Z", "rating": 1, "metadata": {}},

    {"id": "demo_010", "source": "google_play", "text": "Please add dark mode! My eyes hurt using this at night. Every other app has it.", "author": "night_owl", "date": "2026-03-04T23:30:00Z", "rating": 3, "metadata": {"app_version": "3.2.0"}},
    {"id": "demo_011", "source": "reddit", "text": "Feature request: dark mode please! It's 2026 and we still don't have dark mode.", "author": "dark_mode_fan", "date": "2026-03-09T20:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 256}},
    {"id": "demo_012", "source": "google_play", "text": "Would love a dark theme option. The bright white UI is blinding at night.", "author": "theme_request", "date": "2026-03-15T21:15:00Z", "rating": 4, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_013", "source": "reddit", "text": "Seriously need dark mode. This is the #1 missing feature.", "author": "ui_lover", "date": "2026-03-22T18:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 189}},

    {"id": "demo_014", "source": "google_play", "text": "App is extremely slow after the update. Takes 10 seconds to load each page.", "author": "slowpoke", "date": "2026-03-06T12:00:00Z", "rating": 2, "metadata": {"app_version": "3.2.1", "device": "Samsung Galaxy A54"}},
    {"id": "demo_015", "source": "google_play", "text": "Performance is terrible. Everything lags and scrolling is choppy.", "author": "perf_issue", "date": "2026-03-11T09:30:00Z", "rating": 2, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_016", "source": "reddit", "text": "Is it just me or has the app become incredibly slow? Loading times are awful.", "author": "speed_tester", "date": "2026-03-20T14:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 67}},

    {"id": "demo_017", "source": "google_play", "text": "Love the new redesign! The UI looks so much cleaner and more modern.", "author": "happy_user", "date": "2026-03-05T16:00:00Z", "rating": 5, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_018", "source": "google_play", "text": "Great app, been using it for years. The new features are really helpful.", "author": "loyal_fan", "date": "2026-03-14T10:30:00Z", "rating": 5, "metadata": {"app_version": "3.2.1"}},

    {"id": "demo_019", "source": "google_play", "text": "Was charged twice for my subscription. Billing support is not responding.", "author": "billing_victim", "date": "2026-03-08T11:00:00Z", "rating": 1, "metadata": {"app_version": "3.2.0"}},
    {"id": "demo_020", "source": "csv", "text": "Double charged on my credit card for the premium plan. Need a refund ASAP.", "author": "refund_needed", "date": "2026-03-19T09:00:00Z", "rating": 1, "metadata": {}},

    {"id": "demo_021", "source": "google_play", "text": "The onboarding tutorial is confusing. I had no idea how to set up my profile.", "author": "new_user_lost", "date": "2026-03-07T15:00:00Z", "rating": 3, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_022", "source": "reddit", "text": "Just downloaded the app and the setup process is really confusing. Almost gave up.", "author": "newbie_2026", "date": "2026-03-16T12:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 23}},

    {"id": "demo_023", "source": "google_play", "text": "App crashes when I try to upload a photo. Happens every time on the gallery screen.", "author": "photo_bug", "date": "2026-03-21T14:30:00Z", "rating": 1, "metadata": {"app_version": "3.2.1", "device": "iPhone 16 Pro"}},
    {"id": "demo_024", "source": "google_play", "text": "Notifications are broken. I'm not getting any alerts even though they're enabled.", "author": "no_notifs", "date": "2026-03-13T08:00:00Z", "rating": 2, "metadata": {"app_version": "3.2.1"}},
    {"id": "demo_025", "source": "reddit", "text": "The search function is useless. Returns completely irrelevant results every time.", "author": "search_hater", "date": "2026-03-17T11:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 38}},

    {"id": "demo_026", "source": "google_play", "text": "App crashes on launch. Third update in a row with this bug. Uninstalling.", "author": "last_straw", "date": "2026-03-23T07:00:00Z", "rating": 1, "metadata": {"app_version": "3.2.2", "device": "Pixel 9"}},
    {"id": "demo_027", "source": "reddit", "text": "Crash on startup is still happening even after the hotfix. What is going on?", "author": "still_broken", "date": "2026-03-24T10:00:00Z", "rating": None, "metadata": {"subreddit": "r/appname", "upvotes": 201}},
    {"id": "demo_028", "source": "google_play", "text": "Instant crash after splash screen. Tried clearing cache, nothing works.", "author": "done_with_this", "date": "2026-03-25T16:30:00Z", "rating": 1, "metadata": {"app_version": "3.2.2"}},
    {"id": "demo_029", "source": "csv", "text": "Multiple users reporting app crash on startup since version 3.2.1 release.", "author": "support_agent", "date": "2026-03-26T09:00:00Z", "rating": None, "metadata": {}},
    {"id": "demo_030", "source": "google_play", "text": "Please add widget support! Would love to see my stats on home screen.", "author": "widget_fan", "date": "2026-03-20T19:00:00Z", "rating": 4, "metadata": {"app_version": "3.2.1"}},
]


def get_demo_items():
    """Return a copy of the demo dataset."""
    import copy
    return copy.deepcopy(DEMO_ITEMS)
