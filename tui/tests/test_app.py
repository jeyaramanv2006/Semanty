import pytest

from tui.app import FindITApp


class FakeClient:
    async def health(self):
        return {"total_passages_indexed": 2}

    async def directories(self):
        return [{"directory_id": "dir_1", "display_name": "Notes", "file_count": 2, "sync_status": "IDLE"}]

    async def search(self, query, limit=10, offset=0):
        return {
            "query": query,
            "total_available": 1,
            "next_offset": None,
            "results": [{
                "chunk_id": "chunk_1",
                "document_id": "doc_1",
                "filename": "notes.md",
                "location_label": "Lines 1–4",
                "passage_preview": "A remembered passage.",
            }],
        }

    async def passage(self, chunk_id):
        return {
            "filename": "notes.md",
            "location_label": "Lines 1–4",
            "display_path": "~/Notes",
            "text": "A remembered passage.",
        }


class FakeBackend:
    async def ensure_ready(self):
        return {"total_passages_indexed": 2}

    def stop(self):
        pass


@pytest.mark.asyncio
async def test_search_and_inspector_state():
    app = FindITApp(client=FakeClient(), backend=FakeBackend())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.execute_search("remembered passage")
        assert len(app.results) == 1
        assert app.results[0]["chunk_id"] == "chunk_1"
        await app.load_detail("chunk_1")
        assert "A remembered passage." in str(app.query_one("#detail").render())


@pytest.mark.asyncio
async def test_generation_discards_stale_search_results():
    class SlowClient(FakeClient):
        async def search(self, query, limit=10, offset=0):
            if query == "old":
                import asyncio
                await asyncio.sleep(0.05)
            return await super().search(query, limit, offset)

    app = FindITApp(client=SlowClient(), backend=FakeBackend())
    async with app.run_test() as pilot:
        await pilot.pause()
        first = app.execute_search("old")
        second = app.execute_search("new")
        await __import__("asyncio").gather(first, second)
        assert app.active_query == "new"
        assert len(app.results) == 1
