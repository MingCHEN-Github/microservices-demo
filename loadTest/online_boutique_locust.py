# online_boutique_locust.py
#
# Custom Locust workload for Google Online Boutique.
# It approximates the official loadgenerator behavior:
#   - index          (GET /)
#   - setCurrency    (POST /setCurrency)
#   - browseProduct  (GET /product/{id})
#   - addToCart      (POST /cart)
#   - viewCart       (GET /cart)
#   - checkout       (POST /cart/checkout)
#
# Control load with:
#   locust -f online_boutique_locust.py --headless \
#          -u 50 -r 10 --run-time 10m \
#          --host=http://<NODE-IP>:<NODEPORT>

# Step1: activate virtual environment: 
# Step2: find the frontend service ip: kubectl get svc -n online-boutique
# Step3: run locust with the command above:
'''
ubuntu@k8s-master:~$ cd microservices-demo/loadTest/

ubuntu@k8s-master:~/microservices-demo/loadTest$ source ~/locustenv/bin/activate

(locustenv) ubuntu@k8s-master:~/microservices-demo/loadTest$ 
   locust -f online_boutique_locust.py \
  --headless \
  -u 50 \
  -r 10 \
  --run-time 2m \
  --host=http://10.101.1.69:80 \
  --csv onlineboutique_run1

'''



import os
import random
import re
from typing import List, Tuple

from locust import HttpUser, task, between

# Regex to discover product IDs from the homepage HTML.
PRODUCT_HREF_RE = re.compile(r"/product/([A-Za-z0-9\-]+)")


class OnlineBoutiqueUser(HttpUser):
    """
    Simulated end user exercising the Online Boutique frontend.

    We use task weights to encode the mix defined in the original demo:
      index: 1
      setCurrency: 2
      browseProduct: 10
      addToCart: 2
      viewCart: 3
      checkout: 1
    """
    # Per-user "think time" between requests (seconds).
    # Lower values => higher per-user QPS.
    wait_time = between(1.0, 3.0)

    # Basic currencies to randomly switch between.
    CURRENCIES = ["USD", "EUR", "JPY", "GBP", "CAD", "AUD"]

    def on_start(self) -> None:
        """
        Called when a simulated user starts.
        We:
          - hit the index page,
          - extract product IDs,
          - initialize a cart.
        """
        self.product_ids: List[str] = []
        self.cart_items: List[Tuple[str, int]] = []
        self._load_products()

    # ---------- helpers ----------

    def _load_products(self) -> None:
        """
        GET /, then parse HTML to discover product IDs for /product/{id} pages.
        """
        with self.client.get("/", name="index", catch_response=True) as resp:
            if not resp.ok:
                resp.failure(f"Index failed with {resp.status_code}")
                return

            html = resp.text or ""
            self.product_ids = PRODUCT_HREF_RE.findall(html)

            if not self.product_ids:
                # Don't treat as a failure, but log for debugging.
                resp.success()
                return

            resp.success()

    def _choose_product(self) -> str:
        """
        Pick a random product ID; if none are known, refresh from index.
        """
        if not self.product_ids:
            self._load_products()
        if not self.product_ids:
            # Still nothing; give up quietly to avoid spamming errors.
            return ""
        return random.choice(self.product_ids)

    # ---------- tasks (weighted mix) ----------

    @task(1)
    def index(self) -> None:
        """
        Visit the home page.
        """
        self.client.get("/", name="index")

    @task(2)
    def set_currency(self) -> None:
        """
        Change displayed currency via POST /setCurrency.
        """
        currency = random.choice(self.CURRENCIES)
        self.client.post(
            "/setCurrency",
            data={"currency_code": currency},
            name="setCurrency",
        )

    @task(10)
    def browse_product(self) -> None:
        """
        Open a random product detail page: GET /product/{id}.
        """
        pid = self._choose_product()
        if not pid:
            return
        self.client.get(f"/product/{pid}", name="product")

    @task(2)
    def add_to_cart(self) -> None:
        """
        Add a random product to the cart: POST /cart.
        """
        pid = self._choose_product()
        if not pid:
            return

        qty = random.randint(1, 3)
        self.cart_items.append((pid, qty))

        self.client.post(
            "/cart",
            data={"product_id": pid, "quantity": qty},
            name="cart:add",
        )

    @task(3)
    def view_cart(self) -> None:
        """
        View current cart: GET /cart.
        """
        self.client.get("/cart", name="cart:view")

    @task(1)
    def checkout(self) -> None:
        """
        Submit a mock checkout: POST /cart/checkout.
        If the cart is empty, we just skip.
        """
        if not self.cart_items:
            # No items, skip checkout.
            return

        # Minimal form payload that the demo frontend accepts.
        payload = {
            "email": "user@example.com",
            "street_address": "1600 Amphitheatre Parkway",
            "zip_code": "94043",
            "city": "Mountain View",
            "state": "CA",
            "country": "USA",
            "credit_card_number": "4432-8015-6152-0454",
            "credit_card_expiration_month": "12",
            "credit_card_expiration_year": "2027",
            "credit_card_cvv": "123",
        }

        with self.client.post(
            "/cart/checkout",
            data=payload,
            name="cart:checkout",
            catch_response=True,
        ) as resp:
            if resp.ok:
                resp.success()
                # After a successful checkout, empty the cart for the next cycle.
                self.cart_items.clear()
            else:
                resp.failure(f"Checkout failed with {resp.status_code}")
