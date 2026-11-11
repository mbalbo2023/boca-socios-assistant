import asyncio
import os
from playwright.async_api import async_playwright, Browser, Playwright

class SyntheticBrowserEngine:
    """
    Motor de navegación concurrente diseñado para evadir bloqueos de Queue-It.
    Implementa un único presupuesto de navegador pero múltiples contextos aislados.
    """
    def __init__(self, concurrency_limit: int = 5):
        self.concurrency_limit = concurrency_limit
        self.browser: Browser | None = None
        self.playwright: Playwright | None = None

    async def start_engine(self):
        self.playwright = await async_playwright().start()
        # Se lanza una única instancia de Chromium en memoria
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

    async def run_isolated_task(self, worker_id: int, target_url: str):
        # Generación del contexto 100% aislado (Storage, Cookies y Caché independientes)
        context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        page = await context.new_page()
        
        try:
            print(f"[Worker {worker_id}] Iniciando asedio a {target_url}...")
            await page.goto(target_url, wait_until="networkidle")
            
            await asyncio.sleep(2)
            
            cookies = await context.cookies()
            queue_token = next((c['value'] for c in cookies if 'queue-it' in c['name'].lower()), None)
            
            print(f"[Worker {worker_id}] Captura finalizada. Token obtenido: {queue_token is not None}")
            return {"worker_id": worker_id, "token": queue_token, "status": "success"}
            
        except Exception as e:
            print(f"[Worker {worker_id}] Fallo de red o timeout: {str(e)}")
            return {"worker_id": worker_id, "error": str(e), "status": "failed"}
        finally:
            await context.close()

    async def orchestrate_swarm(self, target_url: str):
        await self.start_engine()
        
        print(f"Desplegando enjambre de {self.concurrency_limit} workers concurrentes...")
        tasks = [
            self.run_isolated_task(i, target_url) 
            for i in range(self.concurrency_limit)
        ]
        
        results = await asyncio.gather(*tasks)
        
        await self.browser.close()
        await self.playwright.stop()
        return results

if __name__ == "__main__":
    engine = SyntheticBrowserEngine(concurrency_limit=3)
    target = os.environ.get("SITE_URL")
    if not target:
        raise SystemExit("SITE_URL_REQUIRED")
    asyncio.run(engine.orchestrate_swarm(target))
