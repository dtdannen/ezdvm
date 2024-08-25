# ezdvm
An attempt at a simple, single DVM implementation.

## Install

```commandline
python3.12 -m venv venv
source venv/bin/activate
pip install ezdvm
```

## Create your own DVM

```python
from ezdvm import EZDVM


class WebScraperDVM(EZDVM):
    
    def __init__(self):
        # choose the job request kinds you will listen and respond to
        super().__init__(kinds=[5050])
    
    async def do_work(self, event):
        return "HelloWorld"
    
    async def calculate_price(self, event):
        return 0
    
    async def check_paid(self, event):
        return True


    

```


