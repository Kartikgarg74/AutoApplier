"""Platform handler registry."""

from .greenhouse import GreenhouseHandler
from .lever import LeverHandler
from .linkedin import LinkedInEasyApplyHandler
from .indeed import IndeedHandler
from .workday import WorkdayHandler
from .wellfound import WellfoundHandler
from .naukri import NaukriHandler
from .generic import GenericFormHandler

PLATFORM_HANDLERS = {
    "greenhouse": GreenhouseHandler,
    "lever": LeverHandler,
    "linkedin": LinkedInEasyApplyHandler,
    "indeed": IndeedHandler,
    "workday": WorkdayHandler,
    "wellfound": WellfoundHandler,
    "naukri": NaukriHandler,
    "generic": GenericFormHandler,
}
