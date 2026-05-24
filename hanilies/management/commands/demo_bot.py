from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from hanilies.models import Cake, CakeOrder, Package, PackageOrder, UserProfile


@dataclass
class DemoCredentials:
    username: str
    password: str


DEFAULT_FULL_SCRIPT = [
    "home",
    "login",
    "ai_recommendations",
    "cakes",
    "cake_order",
    "cake_tracking",
    "packages",
    "package_order",
    "package_tracking",
    "profile",
    "ai_recommendations",
    "order_tracking",
]

CUSTOM_SCRIPT_STEPS = [
    "home",
    "login",
    "ai_recommendations",
    "cakes",
    "cake_order",
    "cake_tracking",
    "packages",
    "package_order",
    "package_tracking",
    "profile",
    "order_tracking",
    "about",
    "contact",
]


class Command(BaseCommand):
    help = "Run a browser-driven demo bot for login and ordering flows."

    def add_arguments(self, parser):
        parser.add_argument(
            "scenario",
            nargs="?",
            default="full",
            choices=["login", "cake", "package", "full", "custom"],
            help="Demo flow to run.",
        )
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000",
            help="Base URL of the running Hanilies app.",
        )
        parser.add_argument(
            "--username",
            default="paneldemo",
            help="Demo account username.",
        )
        parser.add_argument(
            "--password",
            default="PanelDemo123!",
            help="Demo account password.",
        )
        parser.add_argument(
            "--browser",
            default="auto",
            choices=["auto", "edge", "chrome"],
            help="Browser to launch for the demo.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="Seconds to pause between visible bot actions.",
        )
        parser.add_argument(
            "--headless",
            action="store_true",
            help="Run the browser without opening a visible window.",
        )
        parser.add_argument(
            "--close-browser",
            action="store_true",
            help="Close the browser automatically after the run.",
        )
        parser.add_argument(
            "--narrate",
            action="store_true",
            help="Narrate the major demo steps using the browser's speech engine.",
        )
        parser.add_argument(
            "--hold-seconds",
            type=float,
            default=0.0,
            help="Seconds to keep the final screen visible before the browser closes.",
        )
        parser.add_argument(
            "--script",
            default="",
            help="Comma-separated scripted steps to run when scenario is custom.",
        )
        parser.add_argument(
            "--payment-mode",
            default="gcash",
            choices=["cod", "gcash"],
            help="Payment mode to demonstrate for cake and package ordering steps.",
        )

    def handle(self, *args, **options):
        self._ensure_selenium_available()
        webdriver, By, Select, EC, WebDriverWait = self._import_selenium_modules()
        self.narrate = options["narrate"]
        self.headless = options["headless"]
        self.driver = None
        self.payment_mode = options["payment_mode"]
        self.last_order_ids = {"cake": None, "package": None}

        credentials = DemoCredentials(
            username=options["username"],
            password=options["password"],
        )
        self.credentials = credentials
        base_url = options["base_url"].rstrip("/")
        delay = max(0.0, options["delay"])
        hold_seconds = max(0.0, options["hold_seconds"])

        self.demo_user = self._seed_demo_data(credentials)
        self.demo_proof_path = self._resolve_demo_proof_path()

        driver = self._build_driver(
            webdriver=webdriver,
            browser_name=options["browser"],
            headless=options["headless"],
        )
        self.driver = driver

        try:
            driver.maximize_window()
        except Exception:
            pass

        wait = WebDriverWait(driver, 20)

        try:
            self._write_step(
                f"Running '{options['scenario']}' demo against {base_url}")

            if options["scenario"] == "login":
                self._run_script(
                    ["login"],
                    driver,
                    wait,
                    By,
                    Select,
                    EC,
                    credentials,
                    base_url,
                    delay,
                )
            elif options["scenario"] == "cake":
                self._run_script(
                    ["login", "cakes", "cake_order", "cake_tracking"],
                    driver,
                    wait,
                    By,
                    Select,
                    EC,
                    credentials,
                    base_url,
                    delay,
                )
            elif options["scenario"] == "package":
                self._run_script(
                    ["login", "packages", "package_order", "package_tracking"],
                    driver,
                    wait,
                    By,
                    Select,
                    EC,
                    credentials,
                    base_url,
                    delay,
                )
            elif options["scenario"] == "custom":
                self._run_script(
                    self._parse_script(options["script"]),
                    driver,
                    wait,
                    By,
                    Select,
                    EC,
                    credentials,
                    base_url,
                    delay,
                )
            else:
                self._run_script(
                    DEFAULT_FULL_SCRIPT,
                    driver,
                    wait,
                    By,
                    Select,
                    EC,
                    credentials,
                    base_url,
                    delay,
                )

            self.stdout.write(self.style.SUCCESS(
                "Demo bot completed successfully."))
            self._announce("The demo bot has finished the walkthrough.")
            if hold_seconds and not options["headless"]:
                self._write_step(
                    f"Holding the final screen for {hold_seconds:.0f} seconds.")
                self._pause(hold_seconds)
        finally:
            if options["close_browser"] or options["headless"]:
                driver.quit()

    def _ensure_selenium_available(self):
        try:
            import selenium  # noqa: F401
        except ImportError as exc:
            raise CommandError(
                "Selenium is not installed. Run 'pip install selenium' first."
            ) from exc

    def _import_selenium_modules(self):
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.select import Select
        from selenium.webdriver.support.ui import WebDriverWait

        return webdriver, By, Select, EC, WebDriverWait

    def _build_driver(self, webdriver, browser_name: str, headless: bool):
        candidates = [browser_name] if browser_name != "auto" else [
            "edge", "chrome"]
        last_error = None

        for candidate in candidates:
            try:
                if candidate == "edge":
                    from selenium.webdriver.edge.options import Options as EdgeOptions

                    options = EdgeOptions()
                    options.use_chromium = True
                    options.add_argument("--start-maximized")
                    if headless:
                        options.add_argument("--headless=new")
                    return webdriver.Edge(options=options)

                if candidate == "chrome":
                    from selenium.webdriver.chrome.options import Options as ChromeOptions

                    options = ChromeOptions()
                    options.add_argument("--start-maximized")
                    if headless:
                        options.add_argument("--headless=new")
                    return webdriver.Chrome(options=options)
            except Exception as exc:
                last_error = exc

        raise CommandError(
            "Unable to launch Edge or Chrome for the demo bot. "
            "Make sure one of those browsers is installed."
        ) from last_error

    def _seed_demo_data(self, credentials: DemoCredentials):
        user, created = User.objects.get_or_create(
            username=credentials.username,
            defaults={
                "email": "paneldemo@example.com",
                "first_name": "Panel",
                "last_name": "Demo",
            },
        )
        if created or not user.check_password(credentials.password):
            user.set_password(credentials.password)
            user.save()

        profile, _ = UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "role": "viewer",
                "phone": "09171234567",
                "address": "123 Demo Street, Lucena City",
            },
        )
        if not profile.phone:
            profile.phone = "09171234567"
        if not profile.address:
            profile.address = "123 Demo Street, Lucena City"
        profile.role = "viewer"
        profile.save()

        if not Cake.objects.filter(is_active=True).exists():
            Cake.objects.create(
                name="Panel Demo Cake",
                category="birthday",
                description="A seeded cake for automated panel presentations.",
                price="1850.00",
                stock=5,
                is_active=True,
            )

        if not Package.objects.filter(status="active").exists():
            Package.objects.create(
                name="Panel Demo Package",
                package_type="kids_birthday",
                description="A seeded event package for automated presentations.",
                base_price="7500.00",
                features="Host\nBackdrop\nBasic styling",
                included_items="Cake\nCupcakes\nBalloons",
                status="active",
            )
        return user

    def _resolve_demo_proof_path(self):
        candidate_paths = [
            settings.BASE_DIR / "static" / "images" / "qr.png",
            settings.BASE_DIR / "static" / "images" / "bg.png",
        ]
        for path in candidate_paths:
            if path.exists():
                return str(path.resolve())
        raise CommandError(
            "No demo proof image was found in static/images. Expected qr.png or bg.png."
        )

    def _write_step(self, message: str):
        self.stdout.write(self.style.NOTICE(message))

    def _announce(self, message: str):
        self._write_step(message)
        if not self.narrate or self.headless or self.driver is None:
            return
        try:
            self.driver.execute_script(
                """
                if ('speechSynthesis' in window) {
                    window.speechSynthesis.cancel();
                    const utterance = new SpeechSynthesisUtterance(arguments[0]);
                    utterance.rate = 1;
                    utterance.pitch = 1;
                    utterance.volume = 1;
                    window.speechSynthesis.speak(utterance);
                }
                """,
                message,
            )
        except Exception:
            pass

    def _pause(self, delay: float):
        if delay > 0:
            time.sleep(delay)

    def _open_page(self, driver, wait, by, url: str, delay: float):
        self._write_step(f"Opening {url}")
        driver.get(url)
        wait.until(lambda browser: browser.execute_script(
            "return document.readyState") == "complete")
        wait.until(lambda browser: browser.find_element(by.TAG_NAME, "body"))
        self._pause(delay)

    def _fill_text(self, element, value: str, delay: float):
        element.clear()
        element.send_keys(value)
        self._pause(delay)

    def _set_dom_value(self, element, value: str, delay: float):
        element.parent.execute_script(
            """
            const field = arguments[0];
            const nextValue = arguments[1];
            field.value = nextValue;
            field.dispatchEvent(new Event('input', { bubbles: true }));
            field.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            element,
            value,
        )
        self._pause(delay)

    def _click(self, element, delay: float):
        try:
            element.parent.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});",
                element,
            )
            element.click()
        except Exception:
            element.parent.execute_script("arguments[0].click();", element)
        self._pause(delay)

    def _pick(self, select_element, visible_text: str, Select, delay: float):
        Select(select_element).select_by_visible_text(visible_text)
        self._pause(delay)

    def _submit_form(self, form_element, delay: float):
        invalid_fields = form_element.parent.execute_script(
            """
            const form = arguments[0];
            return Array.from(form.querySelectorAll(':invalid')).map(
                (field) => field.name || field.id || field.type || 'unknown'
            );
            """,
            form_element,
        )
        if invalid_fields:
            raise CommandError(
                "Demo bot could not submit the form because these fields are invalid: "
                + ", ".join(invalid_fields)
            )
        try:
            form_element.parent.execute_script(
                "arguments[0].requestSubmit();",
                form_element,
            )
        except Exception:
            form_element.submit()
        self._pause(delay)

    def _upload_file(self, file_input, file_path: str, delay: float):
        file_input.send_keys(file_path)
        self._pause(delay)

    def _latest_order_id(self, order_type: str):
        if order_type == "cake":
            return CakeOrder.objects.filter(user=self.demo_user).order_by("-id").values_list("id", flat=True).first()
        return PackageOrder.objects.filter(user=self.demo_user).order_by("-id").values_list("id", flat=True).first()

    def _parse_script(self, script_value: str):
        steps = [step.strip()
                 for step in script_value.split(",") if step.strip()]
        if not steps:
            raise CommandError(
                "Custom scenario requires at least one step in --script."
            )
        invalid_steps = [
            step for step in steps if step not in CUSTOM_SCRIPT_STEPS]
        if invalid_steps:
            raise CommandError(
                "Unknown custom script steps: " + ", ".join(invalid_steps)
            )
        return steps

    def _run_script(self, steps, driver, wait, By, Select, EC, credentials, base_url: str, delay: float):
        handlers = {
            "home": lambda: self._show_homepage(driver, wait, By, base_url, delay),
            "login": lambda: self._run_login_flow(driver, wait, By, EC, credentials, base_url, delay),
            "ai_recommendations": lambda: self._show_recommendations(driver, wait, By, base_url, delay),
            "cakes": lambda: self._show_cakes_catalog(driver, wait, By, base_url, delay),
            "cake_order": lambda: self._run_cake_flow(driver, wait, By, Select, EC, base_url, delay),
            "cake_tracking": lambda: self._show_tracking_page(driver, wait, By, base_url, delay, "cake"),
            "packages": lambda: self._show_packages_catalog(driver, wait, By, base_url, delay),
            "package_order": lambda: self._run_package_flow(driver, wait, By, Select, EC, base_url, delay),
            "package_tracking": lambda: self._show_tracking_page(driver, wait, By, base_url, delay, "package"),
            "profile": lambda: self._show_profile(driver, wait, By, base_url, delay),
            "order_tracking": lambda: self._show_all_tracking(driver, wait, By, base_url, delay),
            "about": lambda: self._show_about(driver, wait, By, base_url, delay),
            "contact": lambda: self._show_contact(driver, wait, By, base_url, delay),
        }

        for step in steps:
            handlers[step]()

    def _show_homepage(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the homepage and welcome experience.")
        self._open_page(driver, wait, By, f"{base_url}/", delay)

    def _show_recommendations(self, driver, wait, By, base_url: str, delay: float):
        if self.last_order_ids["cake"] or self.last_order_ids["package"]:
            self._announce(
                "Returning to the homepage to show personalized AI-style recommendations based on the recorded orders.")
        else:
            self._announce(
                "Showing the recommendation engine before any new demo orders are placed.")
        self._open_page(driver, wait, By, f"{base_url}/", delay)

    def _show_cakes_catalog(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the cakes catalog.")
        self._open_page(driver, wait, By, f"{base_url}/cakes/", delay)

    def _show_packages_catalog(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the event packages catalog.")
        self._open_page(driver, wait, By, f"{base_url}/packages/", delay)

    def _show_profile(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the customer profile summary.")
        self._open_page(driver, wait, By, f"{base_url}/profile/", delay)

    def _show_all_tracking(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the order tracking dashboard.")
        self._open_page(driver, wait, By, f"{base_url}/order-tracking/", delay)

    def _show_about(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the about page.")
        self._open_page(driver, wait, By, f"{base_url}/about/", delay)

    def _show_contact(self, driver, wait, By, base_url: str, delay: float):
        self._announce("Opening the contact page.")
        self._open_page(driver, wait, By, f"{base_url}/contact/", delay)

    def _show_tracking_page(self, driver, wait, By, base_url: str, delay: float, order_type: str):
        order_id = self.last_order_ids.get(
            order_type) or self._latest_order_id(order_type)
        self.last_order_ids[order_type] = order_id
        if order_id:
            self._announce(
                f"Showing the {order_type} order tracking and payment status.")
            self._open_page(
                driver,
                wait,
                By,
                f"{base_url}/order-tracking/?type={order_type}&id={order_id}",
                delay,
            )
        else:
            self._announce(
                "Opening order tracking even though no matching demo order has been created yet.")
            self._open_page(driver, wait, By,
                            f"{base_url}/order-tracking/", delay)

    def _run_login_flow(self, driver, wait, By, EC, credentials: DemoCredentials, base_url: str, delay: float):
        self._open_page(driver, wait, By, f"{base_url}/login/", delay)
        self._announce("Logging in with the demo account.")

        username_input = wait.until(
            EC.visibility_of_element_located((By.NAME, "username")))
        password_input = wait.until(
            EC.visibility_of_element_located((By.NAME, "password")))
        self._announce("Entering the username and password.")
        self._fill_text(username_input, credentials.username, delay)
        self._fill_text(password_input, credentials.password, delay)

        submit_button = driver.find_element(
            By.CSS_SELECTOR, "form button[type='submit']")
        self._announce("Submitting the login form.")
        self._click(submit_button, delay)
        wait.until(lambda browser: "/login/" not in browser.current_url)

    def _run_cake_flow(self, driver, wait, By, Select, EC, base_url: str, delay: float):
        self._open_page(driver, wait, By, f"{base_url}/cake-customize/", delay)
        self._announce("Filling the cake order form.")

        wait.until(EC.visibility_of_element_located(
            (By.ID, "cake-order-form")))
        self._announce("Choosing the cake theme, size, flavor, and frosting.")
        self._pick(driver.find_element(By.NAME, "theme"),
                   "Birthday", Select, delay)
        self._pick(driver.find_element(By.NAME, "size"),
                   "8 inches", Select, delay)
        self._pick(driver.find_element(
            By.NAME, "shape"), "Round", Select, delay)
        self._pick(driver.find_element(By.NAME, "flavor"),
                   "Chocolate", Select, delay)
        self._pick(driver.find_element(By.NAME, "frosting"),
                   "Buttercream", Select, delay)
        self._pick(driver.find_element(By.NAME, "filling"),
                   "Chocolate Ganache", Select, delay)

        self._fill_text(driver.find_element(
            By.NAME, "color_palette"), "Blush pink and gold", delay)
        self._fill_text(driver.find_element(
            By.NAME, "message_on_cake"), "Happy Demo Day Panel", delay)

        addon_boxes = driver.find_elements(By.CSS_SELECTOR, ".addon-checkbox")
        if addon_boxes:
            self._announce("Adding a decoration option to the cake.")
            self._click(addon_boxes[0], delay)

        quantity_input = driver.find_element(By.NAME, "quantity")
        self._fill_text(quantity_input, "1", delay)

        delivery_date = (date.today() + timedelta(days=7)).isoformat()
        self._announce(
            "Entering the delivery details and customer contact information.")
        self._set_dom_value(driver.find_element(
            By.NAME, "delivery_date"), delivery_date, delay)
        self._fill_text(driver.find_element(
            By.NAME, "delivery_address"), "123 Demo Street, Lucena City", delay)
        self._fill_text(
            driver.find_element(By.NAME, "special_instructions"),
            "This order is generated by the live presentation bot.",
            delay,
        )
        self._fill_text(driver.find_element(
            By.NAME, "contact_name"), "Panel Demo", delay)
        self._fill_text(driver.find_element(
            By.NAME, "contact_phone"), "09171234567", delay)
        self._fill_text(driver.find_element(
            By.NAME, "contact_email"), "paneldemo@example.com", delay)

        if self.payment_mode == "gcash":
            self._announce(
                "Switching to GCash to demonstrate payment verification for the cake order.")
            self._click(
                driver.find_element(
                    By.CSS_SELECTOR, "input[name='payment_method'][value='gcash']"),
                delay,
            )
            wait.until(lambda browser: "d-none" not in browser.find_element(By.ID,
                       "gcash-fields").get_attribute("class"))
            self._fill_text(
                driver.find_element(By.NAME, "reference_number"),
                f"CAKE-DEMO-{int(time.time())}",
                delay,
            )
            self._upload_file(driver.find_element(
                By.NAME, "proof_image"), self.demo_proof_path, delay)

        self._announce("Submitting the cake order.")
        self._click(driver.find_element(By.CSS_SELECTOR,
                    "#cake-order-form button[type='submit']"), delay)
        wait.until(lambda browser: "/order-tracking/" in browser.current_url)
        self.last_order_ids["cake"] = self._latest_order_id("cake")

    def _run_package_flow(self, driver, wait, By, Select, EC, base_url: str, delay: float):
        self._open_page(driver, wait, By, f"{base_url}/order-package/", delay)
        self._announce("Filling the package order flow.")

        wait.until(EC.visibility_of_element_located(
            (By.ID, "package-step-one")))
        event_type = driver.find_element(By.NAME, "event_type")
        self._announce("Selecting the package event type and add-ons.")
        self._pick(event_type, "Kid's Birthday", Select, delay)

        addon_boxes = driver.find_elements(By.CSS_SELECTOR, ".package-addon")
        if addon_boxes:
            self._click(addon_boxes[0], delay)

        self._click(driver.find_element(By.CSS_SELECTOR,
                    "#package-step-one button[type='submit']"), delay)
        wait.until(
            lambda browser: "/package-cake-customize/" in browser.current_url)

        wait.until(EC.visibility_of_element_located(
            (By.ID, "package-step-two")))
        self._announce("Customizing the package cake details.")
        self._pick(driver.find_element(By.NAME, "theme"),
                   "Birthday", Select, delay)
        self._pick(driver.find_element(By.NAME, "cake_size"),
                   "Upgrade to 10 inches (+ P500.00)", Select, delay)
        self._pick(driver.find_element(By.NAME, "flavor"),
                   "Chocolate", Select, delay)
        self._pick(driver.find_element(By.NAME, "frosting"),
                   "Buttercream", Select, delay)
        self._pick(driver.find_element(By.NAME, "filling"),
                   "Chocolate Ganache", Select, delay)
        self._pick(driver.find_element(
            By.NAME, "shape"), "Round", Select, delay)
        self._fill_text(driver.find_element(
            By.NAME, "color_palette"), "Blue, white, and gold", delay)
        self._fill_text(driver.find_element(
            By.NAME, "message_on_cake"), "Happy Birthday", delay)

        cake_decoration_boxes = driver.find_elements(
            By.CSS_SELECTOR, ".package-cake-decoration")
        if cake_decoration_boxes:
            self._click(cake_decoration_boxes[0], delay)

        self._fill_text(
            driver.find_element(By.NAME, "cake_instructions"),
            "Keep the style clean and festive for the presentation.",
            delay,
        )
        self._click(driver.find_element(By.CSS_SELECTOR,
                    "#package-step-two button[type='submit']"), delay)
        wait.until(lambda browser: "/package-payment/" in browser.current_url)

        wait.until(EC.visibility_of_element_located(
            (By.ID, "package-step-three")))
        event_date = (date.today() + timedelta(days=14)).isoformat()
        self._announce(
            "Entering the event schedule and final contact details.")
        self._set_dom_value(driver.find_element(
            By.NAME, "event_date"), event_date, delay)
        self._set_dom_value(driver.find_element(
            By.NAME, "event_time"), "14:00", delay)
        self._fill_text(driver.find_element(By.NAME, "venue"),
                        "Hanilies Demo Hall, Lucena City", delay)
        self._fill_text(driver.find_element(
            By.NAME, "contact_name"), "Panel Demo", delay)
        self._fill_text(driver.find_element(
            By.NAME, "contact_phone"), "09171234567", delay)
        self._fill_text(driver.find_element(
            By.NAME, "contact_email"), "paneldemo@example.com", delay)
        if self.payment_mode == "gcash":
            self._announce(
                "Switching to GCash to demonstrate package payment verification.")
            self._click(
                driver.find_element(
                    By.CSS_SELECTOR, "input[name='payment_method'][value='gcash']"),
                delay,
            )
            wait.until(lambda browser: "d-none" not in browser.find_element(By.ID,
                       "package-gcash-fields").get_attribute("class"))
            self._fill_text(
                driver.find_element(By.NAME, "reference_number"),
                f"PACKAGE-DEMO-{int(time.time())}",
                delay,
            )
            self._upload_file(driver.find_element(
                By.NAME, "proof_image"), self.demo_proof_path, delay)
        self._announce("Submitting the package order.")
        self._submit_form(driver.find_element(
            By.ID, "package-step-three"), delay)
        wait.until(lambda browser: "/order-tracking/" in browser.current_url)
        self.last_order_ids["package"] = self._latest_order_id("package")
