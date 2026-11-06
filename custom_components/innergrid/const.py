"""Constants for the Innergrid integration."""

from datetime import timedelta

DOMAIN = "innergrid"
INTEGRATION_NAME = "Innergrid"

CONF_TOPIC_PREFIX = "topic_prefix"
# The REST API of the edge server, optional: it adds the names of the spaces
# and the control of the charge points.
CONF_API_URL = "api_url"
CONF_API_EMAIL = "api_email"
CONF_API_PASSWORD = "api_password"  # noqa: S105

# The config flow waits this long for a first message to check the prefix.
VALIDATION_TIMEOUT = 30
# Seconds to wait before connecting again; doubles up to the maximum.
RECONNECT_INTERVAL = 5
RECONNECT_INTERVAL_MAX = 300
# Data that is not updated for this long is shown as unavailable. Most topics
# are published every 10 to 70 seconds, the Milesight sensors every 3 minutes.
STALE_AFTER = timedelta(minutes=15)
STALE_CHECK_INTERVAL = timedelta(minutes=1)
# The platform's topics are retained, so all of them arrive right after
# connecting. Restored data that is not confirmed within this time is of an
# instance that was removed while Home Assistant was not connected.
REMOVAL_GRACE = timedelta(minutes=2)

# The latest data is stored, so entities show their last values after a
# restart until new data arrives. It is saved at most this often, and when
# Home Assistant stops.
STORAGE_VERSION = 1
STORAGE_SAVE_DELAY = 600
