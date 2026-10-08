"""Programmed HA behavior first; otherwise queue the exact utterance for Luna."""
from datetime import datetime,timezone
import asyncio
import aiohttp
import voluptuous as vol
from homeassistant.components import conversation
from homeassistant.helpers import config_validation as cv,intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .routing import should_dispatch,acknowledgement

DOMAIN='assistant_dispatch'
CONFIG_SCHEMA=vol.Schema({vol.Optional(DOMAIN):vol.Schema({
    vol.Required('relay_url'):cv.url,vol.Required('authorization'):cv.string,
})},extra=vol.ALLOW_EXTRA)


async def async_setup(hass,config):
    if DOMAIN not in config:return True
    entity=AssistantDispatch(config[DOMAIN])
    await hass.data[conversation.DATA_COMPONENT].async_add_entities([entity])
    return True


class AssistantDispatch(conversation.ConversationEntity):
    _attr_name='Assistant dispatch'
    _attr_unique_id='assistant-default-dispatch'
    _attr_supported_features=conversation.ConversationEntityFeature.CONTROL

    def __init__(self,config):
        self.url=config['relay_url'].rstrip('/')+'/v1/agent/prompts'
        self.authorization=config['authorization']

    @property
    def supported_languages(self):return '*'

    async def async_process(self,user_input):
        native=await conversation.async_converse(self.hass,user_input.text,user_input.conversation_id,
            user_input.context,language=user_input.language,agent_id=conversation.HOME_ASSISTANT_AGENT,
            device_id=user_input.device_id)
        if not should_dispatch(native.response.error_code,native.response.success_results,
                               native.response.failed_results):return native
        response=intent.IntentResponse(language=user_input.language)
        body={'id':'ha-'+user_input.context.id,'prompt':user_input.text,
              'timezone':self.hass.config.time_zone,'created_at':datetime.now(timezone.utc).isoformat()}
        try:
            async with async_get_clientsession(self.hass).post(self.url,json=body,
                headers={'Authorization':self.authorization},timeout=aiohttp.ClientTimeout(total=10)) as request:
                if request.status not in (200,201):raise RuntimeError('Relay rejected request.')
                receipt=await request.json()
            response.async_set_speech(acknowledgement(receipt))
        except (aiohttp.ClientError,asyncio.TimeoutError,RuntimeError,KeyError,ValueError):
            response.async_set_error(intent.IntentResponseErrorCode.UNKNOWN,
                'I could not save that request. Please try again.')
        return conversation.ConversationResult(response=response,conversation_id=native.conversation_id,
            continue_conversation=False)
