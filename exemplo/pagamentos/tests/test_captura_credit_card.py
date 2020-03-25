import pytest
import responses
from django.urls import reverse
from model_bakery import baker

from django_pagarme import facade
from django_pagarme.models import PagarmeFormConfig, PagarmeItemConfig, PagarmePayment

TOKEN = 'test_transaction_aJx9ibUmRqYcQrrUaNtQ3arTO4tF1z'


@pytest.fixture
def payment_config(db):
    return baker.make(
        PagarmeFormConfig,
        max_installments=12,
        free_installment=1,
        interest_rate=1.66,
        payments_methods='credit_card'
    )


def test_calculate_amount(payment_config):
    assert payment_config.calculate_amount(9999, 12) == 11991


@pytest.fixture
def payment_item(payment_config):
    return baker.make(
        PagarmeItemConfig,
        tangible=False,
        default_config=payment_config
    )


def test_payment_plans(payment_item):
    payment_item.price = 39700

    assert payment_item.payment_plans == [
        (1, 39700, 39700), 
        (2, 41019, 20509), 
        (3, 41678, 13892), 
        (4, 42337, 10584), 
        (5, 42996, 8599), 
        (6, 43655, 7275), 
        (7, 44314, 6330), 
        (8, 44973, 5621), 
        (9, 45632, 5070), 
        (10, 46291, 4629), 
        (11, 46950, 4268), 
        (12, 47609, 3967),
    ]



@pytest.fixture
def pagarme_responses(transaction_json, captura_json):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, f'https://api.pagar.me/1/transactions/{TOKEN}', json=transaction_json)
        rsps.add(responses.POST, f'https://api.pagar.me/1/transactions/{TOKEN}/capture', json=captura_json)
        yield rsps


@pytest.fixture
def payment_status_listener(mocker):
    mock = mocker.Mock()
    facade.add_payment_status_changed(mock)
    yield mock
    facade._payment_status_changed_listeners.pop()


@pytest.fixture
def resp(client, pagarme_responses, payment_status_listener):
    return client.get(reverse('django_pagarme:capture', kwargs={'token': TOKEN}))


def test_status_code(resp, payment_item):
    assert resp.status_code == 302
    assert resp.url == reverse('django_pagarme:thanks', kwargs={'slug': payment_item.slug})


def test_pagarme_payment_creation(resp):
    assert PagarmePayment.objects.exists()


def test_pagarme_payment_data(resp, transaction_json, payment_item: PagarmeItemConfig):
    payment = PagarmePayment.objects.first()
    assert (
               payment.card_id,
               payment.card_last_digits,
               payment.installments,
               list(payment.items.all()),
               payment.transaction_id
           ) == (
               transaction_json['card']['id'],
               transaction_json['card_last_digits'],
               transaction_json['installments'],
               [payment_item],
               str(transaction_json['id'])
           )


def test_pagarme_payment_initial_configuration(resp):
    payment = facade.find_payment_by_transaction(str(TRANSACTION_ID))
    assert [n.status for n in payment.notifications.all()] == [facade.PAID]


def test_status_listener_executed(resp, payment_status_listener):
    payment = facade.find_payment_by_transaction(str(TRANSACTION_ID))
    payment_status_listener.assert_called_once_with(payment_id=payment.id)


# Testing tampered item price

def _invalid_resp(tampered_item_price_json):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, f'https://api.pagar.me/1/transactions/{TOKEN}', json=tampered_item_price_json)
        yield rsps


@pytest.fixture
def tampered_item_price_json(transaction_json, payment_item: PagarmeItemConfig):
    transaction_json['items'][0]['unit_price'] = payment_item.price - 1
    return transaction_json


@pytest.fixture
def pargarme_tampered_item_price_resps(tampered_item_price_json):
    yield from _invalid_resp(tampered_item_price_json)


@pytest.fixture
def resp_tampered_item_price(client, pargarme_tampered_item_price_resps, logger_exception_mock):
    return client.get(reverse('django_pagarme:capture', kwargs={'token': TOKEN}))


def test_status_code_invalid_item_price(resp_tampered_item_price):
    assert resp_tampered_item_price.status_code == 400


@pytest.fixture
def logger_exception_mock(mocker):
    return mocker.patch('django_pagarme.views.logger.exception')


def test_item_price_error_msg(resp_tampered_item_price, tampered_item_price_json, payment_item, logger_exception_mock):
    unit_price = tampered_item_price_json['items'][0]['unit_price']
    logger_exception_mock.assert_called_once_with(
        f'Valor de item {unit_price} é menor que o esperado {payment_item.price}'
    )


# Test tampered total amount price:

@pytest.fixture
def tampered_authorized_amount_json(transaction_json, payment_item: PagarmeItemConfig):
    transaction_json['authorized_amount'] = payment_item.price - 1
    return transaction_json


@pytest.fixture
def pargarme_tampered_authorized_amount_resps(tampered_authorized_amount_json):
    yield from _invalid_resp(tampered_authorized_amount_json)


@pytest.fixture
def resp_tampered_authorized_amount(client, pargarme_tampered_authorized_amount_resps, logger_exception_mock):
    return client.get(reverse('django_pagarme:capture', kwargs={'token': TOKEN}))


def test_status_code_invalid_authorized_amount(resp_tampered_authorized_amount):
    assert resp_tampered_authorized_amount.status_code == 400


def test_authorized_amount_error_msg(resp_tampered_authorized_amount, tampered_authorized_amount_json, payment_item,
                                     logger_exception_mock):
    authorized_amount = tampered_authorized_amount_json['authorized_amount']
    logger_exception_mock.assert_called_once_with(
        f'Valor autorizado {authorized_amount} é menor que o esperado {payment_item.price}'
    )


# Test tampered installments:

@pytest.fixture
def tampered_installments_json(transaction_json, payment_config: PagarmeFormConfig):
    transaction_json['installments'] = payment_config.max_installments + 1
    return transaction_json


@pytest.fixture
def pargarme_tampered_installments_resps(tampered_installments_json):
    yield from _invalid_resp(tampered_installments_json)


@pytest.fixture
def resp_tampered_installments(client, pargarme_tampered_installments_resps, logger_exception_mock):
    return client.get(reverse('django_pagarme:capture', kwargs={'token': TOKEN}))


def test_status_code_invalid_installments(resp_tampered_installments):
    assert resp_tampered_installments.status_code == 400


def test_installments_error_msg(resp_tampered_installments, tampered_installments_json,
                                payment_config: PagarmeFormConfig, logger_exception_mock):
    installments = tampered_installments_json['installments']
    logger_exception_mock.assert_called_once_with(
        f'Parcelamento em {installments} vez(es) é maior que o máximo {payment_config.max_installments}'
    )


# Test tampered interest)rate:

@pytest.fixture
def tampered_interest_rate_json(transaction_json, payment_config: PagarmeFormConfig, payment_item):
    transaction_json['installments'] = 12  # Should charge interest and amount be 11991 and each installment 9.99
    return transaction_json


@pytest.fixture
def pargarme_tampered_interest_rate_resps(tampered_interest_rate_json):
    yield from _invalid_resp(tampered_interest_rate_json)


@pytest.fixture
def resp_tampered_interest_rate(client, pargarme_tampered_interest_rate_resps, logger_exception_mock):
    return client.get(reverse('django_pagarme:capture', kwargs={'token': TOKEN}))


def test_status_code_invalid_interest_rate(resp_tampered_interest_rate):
    assert resp_tampered_interest_rate.status_code == 400


def test_interest_error_msg(resp_tampered_interest_rate, tampered_installments_json,
                            payment_config: PagarmeFormConfig, logger_exception_mock, payment_item: PagarmeItemConfig):
    installments = tampered_installments_json['installments']
    logger_exception_mock.assert_called_once_with(
        f'Parcelamento em 12 vez(es) com juros 1.66% deveria dar '
        f'{payment_config.calculate_amount(payment_item.price, 12)}'
        f' mas deu '
        f'{payment_item.price}'
    )


TRANSACTION_ID = 7656690


@pytest.fixture
def transaction_json(payment_item: PagarmeItemConfig):
    return {
        'object': 'transaction', 'status': 'authorized', 'refuse_reason': None, 'status_reason': 'antifraud',
        'acquirer_response_code': '0000', 'acquirer_name': 'pagarme', 'acquirer_id': '5cdec7071458b442125d940b',
        'authorization_code': '727706', 'soft_descriptor': None, 'tid': TRANSACTION_ID, 'nsu': TRANSACTION_ID,
        'date_created': '2020-01-21T01:10:13.015Z', 'date_updated': '2020-01-21T01:10:13.339Z',
        'amount': payment_item.price,
        'authorized_amount': payment_item.price, 'paid_amount': 0, 'refunded_amount': 0, 'installments': 1,
        'id': TRANSACTION_ID, 'cost': 70,
        'card_holder_name': 'Bar Baz', 'card_last_digits': '1111', 'card_first_digits': '411111', 'card_brand': 'visa',
        'card_pin_mode': None, 'card_magstripe_fallback': False, 'cvm_pin': False, 'postback_url': None,
        'payment_method': 'credit_card', 'capture_method': 'ecommerce', 'antifraud_score': None, 'boleto_url': None,
        'boleto_barcode': None, 'boleto_expiration_date': None, 'referer': 'encryption_key', 'ip': '177.27.238.139',
        'items': [{
            'object': 'item',
            'id': f'{payment_item.slug}',
            'title': f'{payment_item.name}',
            'unit_price': payment_item.price,
            'quantity': 1, 'category': None, 'tangible': False, 'venue': None, 'date': None
        }], 'card': {
            'object': 'card', 'id': 'card_ck5n7vtbi010or36dojq96sb1', 'date_created': '2020-01-21T01:45:57.294Z',
            'date_updated': '2020-01-21T01:45:57.789Z', 'brand': 'visa', 'holder_name': 'agora captura',
            'first_digits': '411111', 'last_digits': '1111', 'country': 'UNITED STATES',
            'fingerprint': 'cj5bw4cio00000j23jx5l60cq', 'valid': True, 'expiration_date': '1227'
        }

    }


@pytest.fixture
def captura_json(payment_item: PagarmeItemConfig):
    return {
        'object': 'transaction', 'status': 'paid', 'refuse_reason': None, 'status_reason': 'acquirer',
        'acquirer_response_code': '0000', 'acquirer_name': 'pagarme', 'acquirer_id': '5cdec7071458b442125d940b',
        'authorization_code': '408324', 'soft_descriptor': None, 'tid': TRANSACTION_ID, 'nsu': TRANSACTION_ID,
        'date_created': '2020-01-21T01:45:57.309Z', 'date_updated': '2020-01-21T01:47:27.105Z', 'amount': 8000,
        'authorized_amount': payment_item.price,
        'paid_amount': payment_item.price, 'refunded_amount': 0,
        'installments': 1,
        'id': TRANSACTION_ID,
        'cost': 100,
        'card_holder_name': 'agora captura', 'card_last_digits': '1111', 'card_first_digits': '411111',
        'card_brand': 'visa', 'card_pin_mode': None, 'card_magstripe_fallback': False, 'cvm_pin': False,
        'postback_url': None,
        'payment_method': 'credit_card', 'capture_method': 'ecommerce', 'antifraud_score': None,
        'boleto_url': None, 'boleto_barcode': None, 'boleto_expiration_date': None, 'referer': 'encryption_key',
        'ip': '177.27.238.139', 'subscription_id': None, 'phone': None, 'address': None,
        'customer': {
            'object': 'customer', 'id': 2601905, 'external_id': 'captura@gmail.com', 'type': 'individual',
            'country': 'br',
            'document_number': None, 'document_type': 'cpf', 'name': 'Agora Captura', 'email': 'captura@gmail.com',
            'phone_numbers': ['+5512997411854'], 'born_at': None, 'birthday': None, 'gender': None,
            'date_created': '2020-01-21T01:45:57.228Z', 'documents': [
                {'object': 'document', 'id': 'doc_ck5n7vta0010nr36d01k1zzzw', 'type': 'cpf', 'number': '29770166863'}]
        }, 'billing': {
            'object': 'billing', 'id': 1135539, 'name': 'Agora Captura', 'address': {
                'object': 'address', 'street': 'Rua Bahamas', 'complementary': 'Sem complemento', 'street_number': '56',
                'neighborhood': 'Cidade Vista Verde', 'city': 'São José dos Campos', 'state': 'SP',
                'zipcode': '12223770',
                'country': 'br', 'id': 2559019
            }
        }, 'shipping': None,
        'items': [{
            'object': 'item',
            'id': f'{payment_item.slug}',
            'title': f'{payment_item.name}',
            'unit_price': payment_item.price,
            'quantity': 1, 'category': None, 'tangible': False, 'venue': None, 'date': None
        }], 'card': {
            'object': 'card', 'id': 'card_ck5n7vtbi010or36dojq96sb1', 'date_created': '2020-01-21T01:45:57.294Z',
            'date_updated': '2020-01-21T01:45:57.789Z', 'brand': 'visa', 'holder_name': 'agora captura',
            'first_digits': '411111', 'last_digits': '1111', 'country': 'UNITED STATES',
            'fingerprint': 'cj5bw4cio00000j23jx5l60cq', 'valid': True, 'expiration_date': '1227'
        }, 'split_rules': None, 'metadata': {}, 'antifraud_metadata': {}, 'reference_key': None, 'device': None,
        'local_transaction_id': None, 'local_time': None, 'fraud_covered': False, 'fraud_reimbursed': None,
        'order_id': None, 'risk_level': 'very_low', 'receipt_url': None, 'payment': None, 'addition': None,
        'discount': None, 'private_label': None
    }
