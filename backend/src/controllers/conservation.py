from src.services import conservation as service
def list_items(): return service.list_reviews()
def detail(id):
    from src.utils import repository as repo
    return repo.get('conservation_reviews',id)
def create(data): return service.create(data)
