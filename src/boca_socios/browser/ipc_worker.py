import asyncio
import json
from synthetic import SyntheticBrowserEngine

class IPCWorkerOrchestrator:
    """
    Orquestador que comunica el panel/bot principal con el motor de navegación aislado.
    """
    def __init__(self, target_url: str, concurrent_sessions: int = 3):
        self.target_url = target_url
        self.concurrent_sessions = concurrent_sessions
        self.engine = SyntheticBrowserEngine(concurrency_limit=self.concurrent_sessions)

    async def dispatch_job(self):
        print(f"[*] Iniciando Job IPC para {self.concurrent_sessions} sesiones a {self.target_url}")
        results = await self.engine.orchestrate_swarm(self.target_url)
        
        success_count = sum(1 for r in results if r.get('status') == 'success')
        print(f"[*] Job Finalizado. Sesiones exitosas: {success_count}/{self.concurrent_sessions}")
        
        print("--- INICIO PAYLOAD IPC ---")
        print(json.dumps(results))
        print("--- FIN PAYLOAD IPC ---")
        return results

if __name__ == "__main__":
    orchestrator = IPCWorkerOrchestrator("https://soysocio.bocajuniors.com.ar", 3)
    asyncio.run(orchestrator.dispatch_job())
