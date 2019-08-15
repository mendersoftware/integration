/// <reference types="Cypress" />

context('Login', () => {
  beforeEach(() => {
    cy.visit(`${Cypress.config().baseUrl}ui/`);
  });

  it('Logs in using UI', () => {
    cy.location('hash').should('equal', '#/login');

    // enter valid username and password
    cy.get('[id=email]').type(Cypress.env('username'));
    cy.get('[name=password]').type(Cypress.env('password'));
    cy.contains('button', 'Log in').click();

    // confirm we have logged in successfully
    cy.location('hash')
      .should('equal', '#/')
      .then(() => cy.getCookie('JWT').should('have.property', 'value'));

    // now we can log out
    cy.contains('.header-dropdown', Cypress.env('username')).click({ force: true });
    cy.contains('span', 'Log out').click({ force: true });
    cy.location('hash').should('equal', '#/login');
  });

  it('fails to access unknown resource', () => {
    cy.request({
      url: Cypress.config().baseUrl + '/users',
      failOnStatusCode: false
    })
      .its('status')
      .should('equal', 404);
  });

  it('Does not log in with invalid password', () => {
    cy.clearCookies()
    cy.location('hash').should('equal', '#/login');
    cy.get('[id=email]').type(Cypress.env('username'));
    cy.get('[name=password]').type('lewrongpassword');
    cy.contains('button', 'Log in')
      .click()
      .wait(3000);

    // still on /login page plus an error is displayed
    cy.location('hash').should('equal', '#/login');
    cy.contains('There was a problem logging in').should('be.visible');
  });
});
