"""Expose the shared cloud list in the Companion app and Assist."""
from datetime import timedelta
import uuid
import voluptuous as vol
from homeassistant.components.todo import PLATFORM_SCHEMA, TodoItem, TodoItemStatus, TodoListEntity, TodoListEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({vol.Required('url'): cv.url, vol.Required('token'): cv.string})
SCAN_INTERVAL = timedelta(seconds=15)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([CloudGroceries(hass, config['url'], config['token'])], True)


class CloudGroceries(TodoListEntity):
    _attr_name = 'Groceries'
    _attr_unique_id = 'assistant_cloud_groceries'
    _attr_supported_features = TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.DELETE_TODO_ITEM

    def __init__(self, hass, url, token):
        self.session = async_get_clientsession(hass)
        self.url = url.rstrip('/')+'/v1/'
        self.headers = {'Authorization': 'Bearer '+token}
        self.rows = {}

    async def call(self, path, body=None):
        method = self.session.post if body is not None else self.session.get
        async with method(self.url+path, headers=self.headers, **({'json':body} if body is not None else {})) as response:
            if response.status != 200:
                raise HomeAssistantError('The cloud grocery change could not be confirmed. Refresh and try again.')
            return await response.json()

    async def async_update(self):
        data = await self.call('list')
        self.rows = {row['id']:row for row in data['items']}
        self._attr_todo_items = [TodoItem(uid=row['id'], summary=row['name'],
            status=TodoItemStatus.COMPLETED if row['complete'] else TodoItemStatus.NEEDS_ACTION)
            for row in data['items']]

    async def change(self, body):
        await self.call('mutations', {'id':str(uuid.uuid4()), **body})
        await self.async_update()
        self.async_write_ha_state()

    async def async_create_todo_item(self, item):
        await self.change({'operation':'add','items':[{'name':item.summary}]})

    async def async_update_todo_item(self, item):
        await self.async_update()
        row = self.rows.get(item.uid)
        if not row:
            raise HomeAssistantError('This grocery item no longer exists.')
        await self.change({'operation':'update','target':item.uid,'version':row['version'],
            'name':item.summary or row['name'],
            'complete':item.status == TodoItemStatus.COMPLETED if item.status is not None else bool(row['complete'])})

    async def async_delete_todo_items(self, uids):
        await self.async_update()
        for uid in uids:
            if uid in self.rows:
                await self.change({'operation':'delete','target':uid,'version':self.rows[uid]['version']})
