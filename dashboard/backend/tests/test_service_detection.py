from __future__ import annotations

import copy
import unittest

from app.service_detection import score_service


class ServiceDetectionProvenanceTests(unittest.TestCase):
    def test_domain_boundaries_reject_lookalikes_from_every_origin(self) -> None:
        bad_values = (
            "outbound.protection.outlook.com.attacker.example",
            "notoutlook.com",
            "evil-smtp2go.com",
            "smtp2go.com.evil.example",
            "smtp2go.com@evil.example",
            "https://smtp2go.com",
            "smtp2go.com/path",
            "smtp2go.com..",
            "smtp2gо.com",  # Cyrillic o does not become the Latin provider domain.
        )
        for value in bad_values:
            for origin in ("source_reverse_dns", "source_base_domain", "source_as_domain"):
                with self.subTest(value=value, origin=origin):
                    result = score_service({origin: value})
                    self.assertEqual(result["profile"], "unknown")
            with self.subTest(value=value, origin="auth"):
                result = score_service({
                    "spf_results": [{"domain": value, "result": "pass"}],
                    "dkim_results": [{"domain": value, "result": "pass"}],
                }, spf_domains=[value], dkim_domains=[value], dkim_selectors=[value])
                self.assertEqual(result["profile"], "unknown")

    def test_exact_and_subdomain_names_normalize_case_and_root_dot(self) -> None:
        for value in (" SMTP2GO.COM. ", "MAIL.SMTP2GO.COM."):
            with self.subTest(value=value):
                result = score_service({"source_reverse_dns": value})
                self.assertEqual(result["service"], "SMTP2GO")
                self.assertEqual(result["confidence_label"], "Niedrig")
                self.assertEqual(result["evidence_details"][0]["value"], value.strip().lower().rstrip("."))

    def test_overlapping_microsoft_rules_choose_one_specific_match(self) -> None:
        result = score_service({"source_reverse_dns": "mail.outbound.protection.outlook.com"})
        self.assertEqual(result["service"], "Microsoft 365")
        self.assertEqual(result["service_id"], "microsoft365")
        self.assertEqual(result["confidence"], 0.30)
        self.assertEqual(len(result["evidence_details"]), 1)
        self.assertEqual(result["evidence_details"][0]["rule_id"], "microsoft365.outbound_domain")

    def test_ptr_and_base_domain_are_one_group(self) -> None:
        ptr = score_service({"source_reverse_dns": "mail.smtp2go.com"})
        duplicated = score_service({
            "source_reverse_dns": "mail.smtp2go.com", "source_base_domain": "smtp2go.com",
        })
        self.assertEqual(ptr["confidence"], duplicated["confidence"])
        self.assertEqual({item["independence_group"] for item in duplicated["evidence_details"]}, {"network_identity"})
        self.assertEqual({item["origin"] for item in duplicated["evidence_details"]}, {"source_reverse_dns", "source_base_domain"})

    def test_selector_alone_never_identifies_a_provider(self) -> None:
        result = score_service({"dkim_results": [
            {"selector": "outbound.protection.outlook.com", "result": "pass"},
            {"selector": "smtp2go.com", "domain": "example.org", "result": "pass"},
        ]}, dkim_selectors=["smtp2go.com", "smtpservice.net", "microsoft", "amazonaws.com"])
        self.assertEqual(result["profile"], "unknown")
        self.assertEqual(result["evidence_details"], [])

    def test_aggregate_domains_keep_their_origin_and_never_gain_pass(self) -> None:
        result = score_service({
            "source_reverse_dns": "mail.smtp2go.com", "source_base_domain": "smtp2go.com",
            "source_as_name": "DEFT.COM",
        }, spf_domains=["smtp2go.com"], dkim_domains=["smtpservice.net"])
        self.assertEqual(result["service"], "SMTP2GO")
        self.assertLess(result["confidence"], 0.80)
        self.assertEqual(result["confidence_label"], "Mittel")
        auth_details = [item for item in result["evidence_details"] if item["origin"] in {"spf_domains", "dkim_domains"}]
        self.assertEqual(len(auth_details), 2)
        self.assertTrue(all("auth_result" not in item for item in auth_details))
        self.assertTrue(any("SPF-Domain (aggregiert, Ergebnis unbekannt)" in label for label in result["evidence"]))

    def test_two_successful_mechanisms_support_high_provider_confidence(self) -> None:
        result = score_service({
            "spf_results": [{"domain": "mail.smtp2go.com", "result": " PASS "}],
            "dkim_results": [{"domain": "smtpservice.net", "result": "pass", "selector": "s123"}],
        })
        self.assertEqual(result["service"], "SMTP2GO")
        self.assertEqual(result["confidence"], 0.90)
        self.assertEqual(result["confidence_label"], "Hoch")
        self.assertEqual({item["independence_group"] for item in result["evidence_details"]}, {"spf", "dkim"})
        self.assertTrue(all(item["auth_result"] == "pass" for item in result["evidence_details"]))

    def test_authentication_stays_paired_with_its_own_domain(self) -> None:
        result = score_service({
            "source_reverse_dns": "mail.smtp2go.com", "source_as_name": "DEFT.COM",
            "spf_results": [
                {"domain": "smtp2go.com", "result": "fail"},
                {"domain": "example.org", "result": "pass"},
            ],
            "dkim_results": [
                {"domain": "smtpservice.net", "result": "fail"},
                {"domain": "example.org", "result": "pass"},
            ],
        }, spf_domains=["smtp2go.com"], dkim_domains=["smtpservice.net"])
        self.assertEqual(result["service"], "SMTP2GO")
        self.assertLess(result["confidence"], 0.8)
        self.assertEqual({item.get("auth_result") for item in result["evidence_details"] if "auth_result" in item}, {"fail"})

    def test_different_providers_do_not_confirm_each_other(self) -> None:
        result = score_service({
            "spf_results": [{"domain": "smtp2go.com", "result": "pass"}],
            "dkim_results": [{"domain": "outlook.com", "result": "pass"}],
        })
        self.assertEqual(result["confidence"], 0.45)
        self.assertEqual(result["confidence_label"], "Niedrig")
        identity_details = [item for item in result["evidence_details"] if item["origin"] != "source_auth_conflict"]
        self.assertEqual(len(identity_details), 1)

    def test_duplicate_results_and_aggregates_cannot_raise_same_group(self) -> None:
        baseline = score_service({"spf_results": [{"domain": "smtp2go.com", "result": "pass"}]})
        repeated = score_service({"spf_results": [
            {"domain": "smtp2go.com", "result": "pass"},
            {"domain": "smtp2go.com", "result": "pass"},
            {"domain": "smtpservice.net", "result": "pass"},
        ]}, spf_domains=["smtp2go.com"] * 100 + ["smtpservice.net"] * 100)
        self.assertEqual(baseline["confidence"], repeated["confidence"])
        self.assertEqual(len(repeated["evidence_details"]), 4)

    def test_conflicting_successful_provider_identities_cannot_be_high(self) -> None:
        result = score_service({
            "spf_results": [
                {"domain": "smtp2go.com", "result": "pass"},
                {"domain": "outlook.com", "result": "pass"},
            ],
            "dkim_results": [
                {"domain": "smtpservice.net", "result": "pass"},
                {"domain": "onmicrosoft.com", "result": "pass"},
            ],
        })
        self.assertLess(result["confidence"], 0.80)
        self.assertEqual(result["confidence_label"], "Mittel")
        self.assertTrue(any("Mehrdeutige Provider-Herkunft" in label for label in result["evidence"]))
        conflicts = [item for item in result["evidence_details"] if item["origin"] == "source_auth_conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["value"], "Microsoft 365, SMTP2GO")
        self.assertEqual(conflicts[0]["auth_result"], "pass")

    def test_latest_failed_result_does_not_become_pass_from_aggregates(self) -> None:
        result = score_service({"dkim_results": [{"domain": "smtpservice.net", "result": "fail"}]}, dkim_domains=["smtpservice.net"])
        self.assertEqual(result["confidence"], 0.20)
        self.assertEqual(result["evidence_details"][0]["origin"], "dkim_domains")
        self.assertNotIn("auth_result", result["evidence_details"][0])
        self.assertEqual(result["evidence_details"][1]["auth_result"], "fail")

    def test_malformed_result_structures_do_not_create_domain_result_pairs(self) -> None:
        malformed = (
            {"domain": ["smtp2go.com", "example.org"], "result": ["fail", "pass"]},
            [{"domain": ["smtp2go.com", "example.org"], "result": "pass"}],
            [{"domain": "smtp2go.com", "result": ["fail", "pass"]}],
            [{"domain": "smtp2go.com"}, {"result": "pass"}],
            [None, "smtp2go.com", 1],
        )
        for value in malformed:
            with self.subTest(value=value):
                result = score_service({"spf_results": value, "dkim_results": value})
                self.assertLess(result["confidence"], 0.8)
                self.assertFalse(any(item.get("auth_result") == "pass" for item in result["evidence_details"]))

    def test_parsedmarc_name_is_correlated_with_network_identity(self) -> None:
        result = score_service({
            "source_name": "Office 365", "source_type": "ESP",
            "source_reverse_dns": "mail.outbound.protection.outlook.com",
            "source_base_domain": "outlook.com",
        })
        self.assertEqual(result["service"], "Microsoft 365")
        self.assertEqual(result["confidence"], 0.50)
        self.assertEqual({item["independence_group"] for item in result["evidence_details"]}, {"network_identity"})

    def test_unknown_or_untrusted_source_names_cannot_invent_provider(self) -> None:
        for name, source_type in (("Unlisted Mail Provider", "ESP"), ("Microsoft 365", "ISP"), ("Example ISP", "ISP"), ("Unknown", "saas")):
            with self.subTest(name=name, source_type=source_type):
                result = score_service({"source_name": name, "source_type": source_type})
                self.assertEqual(result["service"], "Unbekannt")
                self.assertIsNone(result["service_id"])
                self.assertEqual(result["confidence"], 0)

    def test_hosting_domains_and_asn_names_alone_are_not_mail_products(self) -> None:
        for domain, name in (("amazonaws.com", "AMAZON-02"), ("google.com", "GOOGLE LLC"), ("microsoft.com", "Microsoft Corporation"), ("deft.com", "DEFT.COM")):
            with self.subTest(domain=domain):
                result = score_service({"source_reverse_dns": "host." + domain, "source_as_domain": domain, "source_as_name": name})
                self.assertEqual(result["profile"], "unknown")
        result = score_service({"source_as_name": "notmicrosoft"}, dkim_domains=["outlook.com"])
        self.assertEqual(result["confidence"], 0.20)
        self.assertEqual(len(result["evidence_details"]), 1)

    def test_asn_name_and_domain_are_one_supporting_group(self) -> None:
        baseline = score_service({"source_reverse_dns": "mail.amazonses.com", "source_as_name": "AMAZON-02"})
        duplicate = score_service({"source_reverse_dns": "mail.amazonses.com", "source_as_name": "AMAZON-02", "source_as_domain": "amazonaws.com"})
        self.assertEqual(baseline["confidence"], duplicate["confidence"])
        self.assertEqual(duplicate["confidence"], 0.45)

    def test_dynamic_ip_remains_diagnostic_and_low_confidence(self) -> None:
        result = score_service({"source_ip_address": "8.8.4.4", "source_reverse_dns": "4.4.8.8.dynamic.example.net"})
        self.assertEqual(result["profile"], "dynamic_ip")
        self.assertEqual(result["confidence_label"], "Niedrig")
        self.assertEqual(len(result["evidence_details"]), 2)
        self.assertEqual({item["independence_group"] for item in result["evidence_details"]}, {"network_identity"})

    def test_static_private_or_partial_ip_ptr_does_not_look_dynamic(self) -> None:
        examples = (
            ("8.8.4.4", "8-8-4-4.static.dynamic.example.net"),
            ("8.8.4.4", "18-8-4-40.dynamic.example.net"),
            ("192.168.1.2", "2.1.168.192.dynamic.example.net"),
            ("2001:4860:4860::8888", "dynamic.example.net"),
        )
        for ip, ptr in examples:
            with self.subTest(ip=ip, ptr=ptr):
                result = score_service({"source_ip_address": ip, "source_reverse_dns": ptr})
                self.assertEqual(result["profile"], "unknown")

    def test_detection_is_pure_and_does_not_consult_dmarc_authorization(self) -> None:
        source = {
            "header_from": "customer.example", "passed_dmarc": False,
            "spf_aligned": False, "dkim_aligned": False,
            "spf_results": [{"domain": "smtp2go.com", "result": "pass"}],
            "dkim_results": [{"domain": "smtpservice.net", "result": "pass"}],
        }
        before = copy.deepcopy(source)
        result = score_service(source)
        self.assertEqual(source, before)
        self.assertEqual(result["confidence_label"], "Hoch")
        source.update(passed_dmarc=True, spf_aligned=True, dkim_aligned=True)
        self.assertEqual(score_service(source), result)
        self.assertNotIn("authorized", result)


if __name__ == "__main__":
    unittest.main()
