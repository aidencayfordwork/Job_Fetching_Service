"""Importing this package registers every implemented connector."""

from app.connectors import registry
from app.connectors.adzuna import AdzunaConnector
from app.connectors.ashby import AshbyConnector
from app.connectors.greenhouse import GreenhouseConnector
from app.connectors.himalayas import HimalayasConnector
from app.connectors.jobicy import JobicyConnector
from app.connectors.jooble import JoobleConnector
from app.connectors.lever import LeverConnector
from app.connectors.remoteok import RemoteOkConnector
from app.connectors.remotive import RemotiveConnector
from app.connectors.smartrecruiters import SmartRecruitersConnector
from app.connectors.weworkremotely import WeWorkRemotelyConnector

registry.register(GreenhouseConnector())
registry.register(LeverConnector())
registry.register(AshbyConnector())
registry.register(SmartRecruitersConnector())
registry.register(RemoteOkConnector())
registry.register(RemotiveConnector())
registry.register(WeWorkRemotelyConnector())
registry.register(JobicyConnector())
registry.register(HimalayasConnector())
registry.register(AdzunaConnector())
registry.register(JoobleConnector())
